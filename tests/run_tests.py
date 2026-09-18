from __future__ import annotations

import asyncio
import json
import sys
import unittest

from voiceops.adapters.higgs_realtime import (
    HiggsRealtimeConfig,
    HiggsRealtimeSession,
)
from voiceops.governed_tools import (
    HIGGS_TOOL_DEFINITIONS,
    execute_tool_call,
    inspect_operational_state,
    propose_governed_action,
    submit_user_approval,
)


class TestHiggsRealtimeVoiceOps(unittest.TestCase):
    def test_inspect_operational_state_all(self) -> None:
        telemetry = inspect_operational_state("all")
        self.assertEqual(telemetry["site"], "Guayaquil Operations Hub (GYE-Node-01)")
        self.assertEqual(telemetry["country"], "Ecuador (EC)")
        self.assertIn("subsystems", telemetry)
        subsystems = telemetry["subsystems"]
        self.assertIn("telephony", subsystems)
        self.assertIn("solar_power", subsystems)
        self.assertIn("network_wifi", subsystems)
        self.assertIn("dmx_lighting", subsystems)
        self.assertIn("servers_rack", subsystems)

    def test_inspect_individual_subsystems(self) -> None:
        tel = inspect_operational_state("telephony")
        self.assertEqual(tel["data"]["hardware"], "Grandstream UCM6104 (Firmware 1.0.20.48)")
        self.assertEqual(len(tel["data"]["registered_extensions"]), 4)

        sol = inspect_operational_state("solar_power")
        self.assertEqual(sol["data"]["solar_generation_watts"], 3840)
        self.assertEqual(sol["data"]["battery_charge_pct"], 94.0)

        net = inspect_operational_state("network_wifi")
        ap_ids = [ap["ap_id"] for ap in net["data"]["access_points"]]
        self.assertIn("AP-SolarYard", ap_ids)

        dmx = inspect_operational_state("dmx_lighting")
        self.assertEqual(dmx["data"]["protocol"], "Art-Net / DMX-512 over RS-485 (Universe 1)")

        rack = inspect_operational_state("servers_rack")
        self.assertEqual(rack["data"]["compute_host"], "AMD Radeon AI PRO R9700 Edge Accelerator")

    def test_governed_action_golden_path_approval_spanish(self) -> None:
        prop = propose_governed_action(
            action_type="restart_wifi_ap",
            target_subsystem="network_wifi",
            parameters={"ap_id": "AP-SolarYard"},
        )
        proposal_id = prop["proposal_id"]
        self.assertTrue(proposal_id.startswith("prop_"))
        self.assertTrue(prop["requires_approval"])

        result = submit_user_approval(
            proposal_id=proposal_id,
            utterance="Si, autorizo reiniciar el punto de acceso ahora mismo.",
        )
        self.assertEqual(result["status"], "EXECUTED")
        self.assertEqual(result["action_type"], "restart_wifi_ap")
        self.assertTrue(result["permit_id"].startswith("vxp_"))
        self.assertIn("evidence_sha256", result)
        self.assertGreater(result["htr_seconds_returned"], 0)
        self.assertEqual(result["details"]["execution_status"], "SUCCESS_DEMO_SAFE")

    def test_governed_action_golden_path_approval_english(self) -> None:
        prop = propose_governed_action(
            action_type="switch_solar_bypass",
            target_subsystem="solar_power",
        )
        proposal_id = prop["proposal_id"]

        result = submit_user_approval(
            proposal_id=proposal_id,
            utterance="Yes, proceed and authorize solar bypass immediately.",
        )
        self.assertEqual(result["status"], "EXECUTED")
        self.assertEqual(result["action_type"], "switch_solar_bypass")
        self.assertEqual(result["details"]["htr_metric"]["saved_seconds"], 2400.0 - 4.5)

    def test_governed_action_fail_closed_on_ambiguity(self) -> None:
        prop = propose_governed_action(
            action_type="isolate_solar_phase",
            target_subsystem="solar_power",
        )
        proposal_id = prop["proposal_id"]

        result = submit_user_approval(
            proposal_id=proposal_id,
            utterance="Mmm maybe we should wait a bit, I am not totally sure.",
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["decision"], "REJECTED_OR_AMBIGUOUS")

    def test_governed_action_fail_closed_on_explicit_negation(self) -> None:
        prop = propose_governed_action(
            action_type="reset_sip_trunk",
            target_subsystem="telephony",
        )
        proposal_id = prop["proposal_id"]

        result = submit_user_approval(
            proposal_id=proposal_id,
            utterance="No, cancela la accion, no reiniciar la troncal.",
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["reason"], "explicit_denial_or_negation")

    def test_tool_dispatch_router(self) -> None:
        self.assertEqual(len(HIGGS_TOOL_DEFINITIONS), 3)
        tool_names = [t["name"] for t in HIGGS_TOOL_DEFINITIONS]
        self.assertIn("inspect_operational_state", tool_names)
        self.assertIn("propose_governed_action", tool_names)
        self.assertIn("submit_user_approval", tool_names)

        out = execute_tool_call("inspect_operational_state", {"subsystem": "solar_power"})
        self.assertEqual(out["subsystem"], "solar_power")

    def test_higgs_realtime_session_events(self) -> None:
        async def run_async_test() -> None:
            barge_in_fired = False
            tool_fired = False

            async def on_barge_in() -> None:
                nonlocal barge_in_fired
                barge_in_fired = True

            async def on_tool_event(name: str, args: dict, output: dict) -> None:
                nonlocal tool_fired
                tool_fired = True

            session = HiggsRealtimeSession(
                on_barge_in=on_barge_in,
                on_tool_event=on_tool_event,
            )

            # 1. Test Session Update Config
            msg = session.get_session_update_message()
            self.assertEqual(msg["type"], "session.update")
            self.assertEqual(len(msg["session"]["tools"]), 3)
            self.assertEqual(msg["session"]["input_audio_format"], "pcm16")

            # 2. Test Interruption / Barge-In event
            res = await session.handle_server_event({"type": "input_audio_buffer.speech_started"})
            self.assertIsNotNone(res)
            self.assertEqual(res["action"], "barge_in_triggered")
            self.assertTrue(barge_in_fired)

            # 3. Test Mid-conversation Tool Call event
            prop_res = propose_governed_action("restart_wifi_ap", "network_wifi")
            pid = prop_res["proposal_id"]

            tool_event = {
                "type": "response.function_call_arguments.done",
                "call_id": "call_test_123",
                "name": "submit_user_approval",
                "arguments": json.dumps({"proposal_id": pid, "utterance": "Si, autorizo."}),
            }
            tool_res = await session.handle_server_event(tool_event)
            self.assertIsNotNone(tool_res)
            self.assertEqual(tool_res["action"], "function_executed")
            self.assertTrue(tool_fired)
            self.assertEqual(tool_res["record"]["output"]["status"], "EXECUTED")

        asyncio.run(run_async_test())


if __name__ == "__main__":
    unittest.main()
