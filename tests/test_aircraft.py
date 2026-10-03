import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wtflight.core.aircraft import BUNDLED, AircraftDatabase, download_database


class AircraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = AircraftDatabase.load(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_snapshot_alias_and_unknown_aircraft(self):
        self.assertEqual(self.db.version, "2.59.0.28")
        self.assertEqual(self.db.resolve("f-86f-2"), self.db.resolve("f-86f-25"))
        self.assertIsNone(self.db.resolve("not_an_aircraft"))
        self.assertEqual(self.db.limits("not_an_aircraft", {"Mfuel, kg": 100}), {})
        self.assertIsNotNone(self.db.resolve("F_16C_BLOCK_50.blkx"))

    def test_known_limits_fuel_dependency_and_missing_fuel(self):
        light = self.db.limits("f_16c_block_50", {"Mfuel, kg": 1000})
        heavy = self.db.limits("f_16c_block_50", {"Mfuel, kg": 5000})
        self.assertEqual(light["ias_kmh"], 1555)
        self.assertEqual(light["mach"], 2.2)
        self.assertEqual(light["gear_kmh"], 482)
        self.assertGreater(light["positive_g"], heavy["positive_g"])
        self.assertLess(light["negative_g"], heavy["negative_g"])
        self.assertAlmostEqual(light["positive_g"], 2 * 770000 / ((9031 + 1000) * 9.81))
        self.assertNotIn("positive_g", self.db.limits("f_16c_block_50", {}))

    def test_variable_sweep_uses_conservative_fallback(self):
        unknown = self.db.limits("f_14a_early", {})
        half = self.db.limits("f_14a_early", {"wing sweep, %": 50})
        self.assertEqual(unknown["ias_kmh"], 1021)
        self.assertTrue(unknown["_sweep_conservative"])
        self.assertEqual(half["ias_kmh"], 1360)
        self.assertNotIn("_sweep_conservative", half)

    def test_failed_update_keeps_old_cache(self):
        target = Path(self.temp.name) / "aircraft_database.json"
        target.write_text('existing snapshot', encoding="utf-8")
        responses = [io.BytesIO(b"2.60.0.1"),
                     io.BytesIO((BUNDLED / "fm_data_db.csv").read_bytes()),
                     io.BytesIO(b"corrupt names file")]
        with patch("wtflight.core.aircraft.urlopen", side_effect=responses):
            with self.assertRaises(ValueError):
                download_database(self.temp.name, "2.59.0.28")
        self.assertEqual(target.read_text(), "existing snapshot")

    def test_successful_update_is_loadable(self):
        responses = [io.BytesIO(b"2.60.0.1"),
                     io.BytesIO((BUNDLED / "fm_data_db.csv").read_bytes()),
                     io.BytesIO((BUNDLED / "fm_names_db.csv").read_bytes())]
        with patch("wtflight.core.aircraft.urlopen", side_effect=responses):
            updated = download_database(self.temp.name, "2.59.0.28")
        self.assertEqual(updated.version, "2.60.0.1")
        self.assertEqual(AircraftDatabase.load(self.temp.name).version, "2.60.0.1")


if __name__ == "__main__":
    unittest.main()
