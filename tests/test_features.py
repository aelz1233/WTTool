import unittest

from wtflight.core._features import (
    AlertCooldown,
    FuelEstimator,
    LayoutHistory,
    add_margins,
    alert_levels,
    metric_risk,
    validate_profile,
)
from wtflight.core.metrics import available_metrics, engine_metric_ids, expand_engine_metric, metric_label, metric_value
from wtflight.ui.main_window import warning_for


class FeatureTests(unittest.TestCase):
    def test_history_isolated_profiles_and_redo_branch(self):
        history = LayoutHistory()
        profiles = {'a': [{'x': .1}], 'b': []}
        history.record(profiles)
        profiles['a'][0]['x'] = .7
        history.record(profiles)
        self.assertEqual(history.undo('a'), [{'x': .1}])
        self.assertIsNone(history.undo('b'))
        self.assertEqual(history.redo('a'), [{'x': .7}])
        history.undo('a')
        profiles['a'][0]['x'] = .4
        history.record(profiles)
        self.assertIsNone(history.redo('a'))

    def test_fuel_rate_and_resets(self):
        estimator = FuelEstimator()
        for second in range(11):
            result = estimator.update('jet', 1000 - second * 2, second)
        self.assertAlmostEqual(result['fuel_flow'], 120)
        self.assertAlmostEqual(result['fuel_seconds'], 490)
        self.assertEqual(estimator.update('jet', 1100, 11), {})
        self.assertEqual(estimator.update('jet', 1098, 20), {})
        self.assertEqual(estimator.update('other', 500, 21), {})
        self.assertEqual(estimator.update('other', None, 22), {})

    def test_no_false_endurance_without_consumption(self):
        estimator = FuelEstimator()
        for second in range(10):
            result = estimator.update('plane', 100, second)
        self.assertEqual(result, {'fuel_flow': 0})

    def test_margins_and_alert_categories(self):
        state = {'IAS, km/h': 950, 'Ny': -4, 'M': .8, 'fuel_seconds': 50}
        limits = {'ias_kmh': 1000, 'positive_g': 10, 'negative_g': -4, 'mach': 1.2}
        add_margins(state, limits)
        self.assertEqual(state['ias_margin'], 50)
        self.assertEqual(state['g_margin_neg'], 0)
        self.assertEqual(alert_levels(state, limits),
                         {'speed': 'caution', 'g': 'critical', 'fuel': 'critical'})
        self.assertEqual(alert_levels({}, {}), {})

    def test_alert_cooldown_escalation_and_disabled_category(self):
        cooldown = AlertCooldown()
        self.assertEqual(cooldown.choose({'speed': 'caution'}, 0, 8, {}), 'speed')
        self.assertIsNone(cooldown.choose({'speed': 'caution'}, 2, 8, {}))
        self.assertEqual(cooldown.choose({'speed': 'critical'}, 3, 8, {}), 'speed')
        self.assertIsNone(cooldown.choose({'fuel': 'critical'}, 4, 8, {'fuel': False}))
        self.assertEqual(cooldown.choose({'speed': 'critical'}, 11, 8, {}), 'speed')

    def test_positive_and_negative_g_reserves_warn_only_for_their_own_limit(self):
        limits = {'positive_g': 10, 'negative_g': -4}
        self.assertEqual(metric_risk('g_margin_pos', {'Ny': 10}, limits), 1)
        self.assertEqual(metric_risk('g_margin_neg', {'Ny': 10}, limits), 0)
        self.assertEqual(metric_risk('g_margin_pos', {'Ny': -4}, limits), 0)
        self.assertEqual(metric_risk('g_margin_neg', {'Ny': -4}, limits), 1)

    def test_profile_validation_and_unique_ids(self):
        payload = {'format': 'wt-flight-profile', 'version': 1,
                   'groups': [{'metrics': ['ias', 'g'], 'x': .2}]}
        first = validate_profile(payload)
        self.assertNotEqual(first[0]['id'], validate_profile(payload)[0]['id'])
        self.assertEqual(first[0]['metrics'], ['ias', 'g'])
        payload['groups'][0]['x'] = float('nan')
        with self.assertRaises(ValueError):
            validate_profile(payload)
        payload['groups'] = []
        self.assertEqual(validate_profile(payload), [])

    def test_all_engines_expand_and_individual_engine_can_be_saved(self):
        state = {"RPM 1": 2_010, "RPM 2": 2_060, "power 1, hp": 1_120,
                 "power 2, hp": 1_180, "thrust 1, kgs": 430, "thrust 2, kgs": 445}
        self.assertEqual(engine_metric_ids("rpm", state), ["engine:rpm:1", "engine:rpm:2"])
        self.assertEqual(expand_engine_metric("power", state), ["engine:power:1", "engine:power:2"])
        self.assertEqual(metric_value("engine:power:2", state, {}), "1180 л.с.")
        self.assertEqual(metric_label("engine:thrust:2"), "Тяга, двигатель 2")
        available = available_metrics(state, {})
        self.assertIn("engine:power:2", available)
        self.assertNotIn("state:power 2, hp", available)
        profile = {"format": "wt-flight-profile", "version": 1,
                   "groups": [{"metrics": ["engine:power:2"]}]}
        self.assertEqual(validate_profile(profile)[0]["metrics"], ["engine:power:2"])

    def test_empty_group_roundtrip_and_numeric_engine_order(self):
        profile = {"format": "wt-flight-profile", "version": 1, "groups": [{"metrics": []}]}
        self.assertEqual(validate_profile(profile)[0]['metrics'], [])
        state = {"RPM 4": 400, "RPM 2": 200, "RPM 1": 100, "RPM 3": 300}
        self.assertEqual(engine_metric_ids('rpm', state), [f'engine:rpm:{i}' for i in range(1, 5)])

    def test_critical_fuel_above_early_threshold_still_warns(self):
        state = {'fuel_seconds': 100, '_fuel_minutes': 1, '_fuel_critical_seconds': 120}
        self.assertEqual(warning_for(('live', state, {}), {})[0], 'critical')
        self.assertEqual(alert_levels(state, {}, fuel_minutes=1, fuel_critical_seconds=120)['fuel'], 'critical')

    def test_stall_warning_uses_configured_aoa_and_prioritizes_audio(self):
        state = {"AoA, deg": 13.5, "_aoa_limit": 15}
        self.assertEqual(alert_levels(state, {}, aoa_limit=15), {"stall": "caution"})
        state["AoA, deg"] = 15
        self.assertEqual(alert_levels(state, {}, aoa_limit=15), {"stall": "critical"})
        self.assertEqual(metric_risk("aoa", state, {}), 1)
        state.update({"fuel_seconds": 50, "_fuel_minutes": 3})
        severity, message = warning_for(("live", state, {}), {})
        self.assertEqual(severity, "critical")
        self.assertIn("ВОЗМОЖНО СВАЛИВАНИЕ", message)
        cooldown = AlertCooldown()
        self.assertEqual(cooldown.choose({"speed": "critical", "stall": "critical"}, 0, 8, {}), "stall")

    def test_warning_categories_and_thresholds_are_applied(self):
        limits = {"ias_kmh": 1000}
        early = {"IAS, km/h": 850, "_warning_ratio": .8}
        self.assertEqual(warning_for(("live", early, {}), limits)[0], "caution")
        early["_warning_categories"] = {"speed": False}
        self.assertEqual(warning_for(("live", early, {}), limits), ("unset", "Пределы не настроены"))
        fuel = {"fuel_seconds": 100, "_fuel_minutes": 3, "_fuel_critical_seconds": 120}
        self.assertEqual(warning_for(("live", fuel, {}), {})[0], "critical")
        levels = alert_levels({"IAS, km/h": 850}, limits, caution_ratio=.8,
                              categories={"speed": True, "g": False, "fuel": False, "stall": False})
        self.assertEqual(levels, {"speed": "caution"})


if __name__ == '__main__':
    unittest.main()
