"""Telemetry degradation checks using local responses, without the game."""
import io
import json
import unittest
from http.client import IncompleteRead
from unittest.mock import patch

from wtflight.services.telemetry import Telemetry


class TelemetryTests(unittest.TestCase):
    def sample(self, responses):
        worker = Telemetry()
        samples = []
        def receive(*args):
            samples.append(args)
            worker.stop_event.set()
        worker.sample.connect(receive)
        with patch('wtflight.services.telemetry.urlopen', side_effect=responses):
            worker.run()
        return samples[0]

    def test_offline_invalid_and_live_responses(self):
        self.assertEqual(self.sample([OSError('offline')])[0], 'offline')
        self.assertEqual(self.sample([io.BytesIO(b'[]')])[0], 'waiting')
        self.assertEqual(self.sample([io.BytesIO(b'bad json')])[0], 'offline')
        state = {'valid': True, 'IAS, km/h': 900}
        result = self.sample([io.BytesIO(json.dumps(state).encode()), OSError('no indicators')])
        self.assertEqual(result, ('live', state, {}))

    def test_truncated_http_body_does_not_kill_polling(self):
        self.assertEqual(self.sample([IncompleteRead(b'partial')])[0], 'offline')
