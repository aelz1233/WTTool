"""Settings recovery and migration must preserve usable user layouts."""
import json
import tempfile
import unittest
from pathlib import Path

from wtflight.core.settings import Settings
from wtflight.ui.main_window import default_profile


class SettingsTests(unittest.TestCase):
    def test_valid_profile_ids_empty_groups_and_preferences_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            groups = default_profile()
            groups[0]['metrics'] = []
            original = {'version': 4, 'profiles': {'default': groups}, 'theme': 'arctic',
                        'limits': {'default': {'_auto': False, 'ias_kmh': 900}},
                        'language': 'en', 'flight': {'telemetry_hz': 15}}
            path.write_text(json.dumps(original), encoding='utf-8')
            settings = Settings(path)
            self.assertEqual([g['id'] for g in settings.groups('default')], [g['id'] for g in groups])
            self.assertEqual(settings.groups('default')[0]['metrics'], [])
            self.assertEqual(settings.data['theme'], 'arctic')
            self.assertFalse(settings.limits('default')['_auto'])
            settings.save()
            self.assertEqual(Settings(path).data, settings.data)

    def test_malformed_types_recover_without_overwriting_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            original = {'version': 'broken', 'profiles': {'default': [None]},
                        'limits': None, 'flight': {'telemetry_hz': 0, 'warning_ratio': 'oops',
                                                'sound_categories': None},
                        'preview': None, 'hotkeys': {'menu': []}}
            content = json.dumps(original)
            path.write_text(content, encoding='utf-8')
            settings = Settings(path)
            self.assertTrue(settings.groups('default'))
            self.assertEqual(settings.data['flight']['telemetry_hz'], 10)
            self.assertEqual(settings.data['flight']['warning_ratio'], 90)
            self.assertEqual(settings.data['limits'], {})
            settings.save()
            backup = next(Path(directory).glob('settings.recovery-*.json'))
            self.assertEqual(backup.read_text(encoding='utf-8'), content)

    def test_broken_json_is_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text('{broken', encoding='utf-8')
            settings = Settings(path)
            settings.save()
            backup = next(Path(directory).glob('settings.recovery-*.json'))
            self.assertEqual(backup.read_text(encoding='utf-8'), '{broken')
