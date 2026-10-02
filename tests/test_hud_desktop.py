"""Desktop regression checks. Uses a temporary profile, never the user's settings.

Run with: .venv/Scripts/python.exe -m unittest test_hud_desktop -v
"""

import ctypes
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from PySide6.QtCore import QPoint, QPointF, Qt, QSize, QEvent
from PySide6.QtGui import QKeySequence, QImage, QColor, QWheelEvent, QFontInfo, QPainter, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from wtflight.ui import main_window as wt_qt
from wtflight.ui import feature_controls as wt_feature_ui
from wtflight.win32.hotkey import GlobalHotkey


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(wt_qt.STYLE)
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.qt_errors = []
        self.old_excepthook = sys.excepthook
        sys.excepthook = lambda kind, value, tb: self.qt_errors.append(str(value))
        self.temp = tempfile.TemporaryDirectory()
        self.previous_path = wt_qt.CONFIG_PATH
        self.previous_feature_path = wt_feature_ui.CONFIG_PATH
        wt_qt.CONFIG_PATH = Path(self.temp.name) / "settings.json"
        wt_feature_ui.CONFIG_PATH = wt_qt.CONFIG_PATH
        self.window = wt_qt.MainWindow(start_background_updates=False)
        self.window.telemetry.stop()
        QTest.qWait(20)

    def tearDown(self):
        self.window.stop_feature_timers()
        self.window.quick_settings.hide()
        self.window.close_hotkeys()
        self.window.tray.hide()
        self.window.hide()
        for overlay in self.window.overlays:
            overlay.close()
        self.window.deleteLater()
        QTest.qWait(20)
        wt_qt.CONFIG_PATH = self.previous_path
        wt_feature_ui.CONFIG_PATH = self.previous_feature_path
        self.temp.cleanup()
        sys.excepthook = self.old_excepthook
        self.assertEqual(self.qt_errors, [], "Unhandled exception in a Qt signal/event")

    def test_compact_windows_and_independent_menu(self):
        w = self.window
        w.show()
        QTest.qWait(20)
        self.assertEqual(w.size().toTuple(), (720, 560))
        w.show_hud()
        w.toggle_quick_settings()
        self.assertTrue(w.quick_settings.isVisible())
        self.assertFalse(w.isVisible())
        self.assertEqual(w.quick_settings.width(), 380)
        self.assertLess(w.quick_settings.height(), 600)
        w.toggle_quick_settings()
        self.assertFalse(w.quick_settings.isVisible())
        self.assertFalse(w.isVisible())

    def test_layout_undo_redo_delete_and_preset(self):
        w = self.window
        before = copy.deepcopy(w.groups())
        w.selected_id = before[0]['id']
        w.delete_group()
        self.assertEqual(len(w.groups()), len(before) - 1)
        w.undo_layout()
        self.assertEqual(w.groups(), before)
        w.redo_layout()
        self.assertEqual(len(w.groups()), len(before) - 1)
        w.preset_box.setCurrentIndex(1)
        w.apply_preset()
        self.assertEqual([g['metrics'] for g in w.groups()],
                         [g['metrics'] for g in w.preset_groups('engine')])
        w.undo_layout()
        self.assertEqual(len(w.groups()), len(before) - 1)

    def test_empty_group_can_be_created_from_main_screen(self):
        w = self.window
        w.tabs.setCurrentIndex(0)
        before = len(w.groups())
        w.create_empty_group()
        group = w.selected_group()
        self.assertEqual(len(w.groups()), before + 1)
        self.assertEqual(group["metrics"], [])
        self.assertTrue(group["title_visible"])
        self.assertEqual(group["title"], "НОВАЯ ГРУППА")

    def test_saved_config_can_be_overwritten_and_deleted(self):
        w = self.window
        w.settings.data["saved_layouts"] = {"Мой конфиг": copy.deepcopy(w.groups())}
        w.refresh_presets()
        saved_data = ("saved", "Мой конфиг")
        w.select_preset(saved_data)
        self.assertTrue(w.overwrite_preset_button.isEnabled())
        self.assertTrue(w.delete_preset_button.isEnabled())
        self.assertTrue(w.overwrite_main_preset_button.isEnabled())
        w.groups()[0]["x"] = .42
        w.overwrite_preset()
        self.assertEqual(w.settings.data["saved_layouts"]["Мой конфиг"][0]["x"], .42)
        with patch.object(wt_feature_ui.QMessageBox, "question", return_value=wt_feature_ui.QMessageBox.StandardButton.Yes):
            w.delete_preset()
        self.assertNotIn("Мой конфиг", w.settings.data["saved_layouts"])
        self.assertFalse(w.overwrite_preset_button.isEnabled())
        self.assertFalse(w.delete_preset_button.isEnabled())

    def test_helicopter_tab_lists_live_rotor_fields_and_applies_layout(self):
        w = self.window
        state = {"valid": True, "IAS, km/h": 190, "H, m": 450, "Vy, m/s": 3,
                 "Ny": 1.2, "RPM 1": 2200, "rotor RPM, %": 96,
                 "throttle 1, %": 82, "Mfuel, kg": 380}
        w.present_sample("live", state, {"type": "ah_64d", "compass": 90})
        labels = [w.helicopter_values.item(index).text() for index in range(w.helicopter_values.count())]
        self.assertTrue(any("rotor RPM" in label for label in labels))
        w.apply_helicopter_preset()
        self.assertEqual([group["metrics"] for group in w.groups()],
                         [group["metrics"] for group in w.preset_groups("helicopter")])

    def test_demo_buffers_real_data_and_database_refresh(self):
        w = self.window
        w.audio = Mock()
        w.set_demo_mode(True)
        self.assertEqual(w.sample[0], 'demo')
        w.on_sample('live', {'valid': True, 'IAS, km/h': 700}, {'type': 'f_16c_block_50'})
        self.assertEqual(w.sample[0], 'demo')
        w.on_database_update(w.database, '')
        self.assertEqual(w.last_real_sample[0], 'live')
        w.process_audio()
        w.audio.play.assert_not_called()
        w.set_demo_mode(False)
        self.assertEqual(w.sample[0], 'live')
        self.assertEqual(w.sample[1]['IAS, km/h'], 700)

    def test_engine_group_expands_to_every_engine_in_live_telemetry(self):
        w = self.window
        group = w.groups()[3]
        group["metrics"] = ["power", "rpm", "thrust"]
        state = {"valid": True, "power 1, hp": 1100, "power 2, hp": 1200,
                 "RPM 1": 2000, "RPM 2": 2100, "thrust 1, kgs": 410, "thrust 2, kgs": 430}
        w.present_sample("live", state, {"type": w.aircraft})
        view = next(view for view in w.canvas.views if view.group["id"] == group["id"])
        rows = view.lines()
        self.assertEqual([row[3] for row in rows],
                         ["engine:power:1", "engine:power:2", "engine:rpm:1", "engine:rpm:2",
                          "engine:thrust:1", "engine:thrust:2"])
        self.assertEqual(rows[1][0], "PWR2")
        self.assertEqual(rows[1][1], "1200 л.с.")
        self.assertIn("engine:power:2", w.available)

    def test_telemetry_rate_and_aoa_limit_preferences_apply_without_restart(self):
        w = self.window
        self.assertAlmostEqual(w.telemetry.interval, .1)
        w.telemetry_rate_box.setCurrentIndex(w.telemetry_rate_box.findData(15))
        w.aoa_limit_spin.setValue(12)
        self.assertAlmostEqual(w.telemetry.interval, 1 / 15)
        self.assertEqual(w.settings.data["flight"]["telemetry_hz"], 15)
        w.present_sample("live", {"valid": True, "AoA, deg": 12}, {"type": w.aircraft})
        self.assertEqual(w.sample[1]["_aoa_limit"], 12)
        self.assertEqual(wt_qt.warning_for(w.sample, w.current_limits())[0], "critical")

    def test_warning_preferences_persist_and_hide_disabled_category(self):
        w = self.window
        w.warning_ratio_spin.setValue(80)
        w.fuel_critical_spin.setValue(90)
        w.warning_checks["speed"].setChecked(False)
        flight = w.settings.data["flight"]
        self.assertEqual(flight["warning_ratio"], 80)
        self.assertEqual(flight["fuel_critical_seconds"], 90)
        self.assertFalse(flight["warning_categories"]["speed"])
        state = {"valid": True, "IAS, km/h": 1200}
        w.present_sample("live", state, {"type": w.aircraft})
        self.assertEqual(wt_qt.warning_for(w.sample, {"ias_kmh": 1000})[0], "unset")

    def test_visibility_preferences(self):
        w = self.window
        w.hud_visible = True
        w.overlay_editing = False
        with patch('wtflight.ui.feature_controls.game_is_foreground', return_value=True):
            self.assertFalse(w.should_show_hud())
            w.on_sample('live', {'valid': True}, {'type': 'unknown'})
            self.assertTrue(w.should_show_hud())
        with patch('wtflight.ui.feature_controls.game_is_foreground', return_value=False):
            self.assertFalse(w.should_show_hud())
            w.hide_other_check.setChecked(False)
            self.assertTrue(w.should_show_hud())
        w.hud_visible = False
        self.assertFalse(w.should_show_hud())

    def test_scene_coordinates_snapping_and_zoom(self):
        w = self.window
        w.show()
        w.canvas.set_screen_size(QSize(1920, 1080))
        w.canvas.set_zoom(1)
        self.assertEqual(w.canvas.sceneRect().size().toSize(), QSize(1920, 1080))
        self.assertEqual(w.canvas.transform().m11(), 1)
        view = w.canvas.views[0]
        self.assertEqual(w.canvas.snap_position(view, 4, 4), (0, 0))
        w.canvas.select(view.group['id'])
        w.selected_id = view.group['id']
        w.align_selected('right')
        self.assertAlmostEqual(w.selected_group()['x'], 1 - w.canvas.views[0].width() / 1920)
        w.canvas.set_zoom(0)
        self.assertAlmostEqual(w.canvas.transform().m11(), w.canvas.transform().m22())

    def test_invalid_import_preserves_layout(self):
        w = self.window
        original = copy.deepcopy(w.groups())
        path = Path(self.temp.name) / 'invalid.json'
        path.write_text('{"format":"wrong","groups":[]}', encoding='utf-8')
        with self.assertRaises(ValueError):
            w.load_profile_file(path)
        self.assertEqual(w.groups(), original)

    def test_scaled_canvas_drag_and_keyboard_undo(self):
        w = self.window
        w.show()
        w.activateWindow()
        QTest.qWait(30)
        canvas = w.canvas
        view = canvas.views[0]
        group_id = view.group['id']
        old = (view.group['x'], view.group['y'])
        point = canvas.mapFromScene(view.graphicsProxyWidget().sceneBoundingRect().center())
        QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=point)
        QTest.mouseMove(canvas.viewport(), point + QPoint(-30, 30), delay=20)
        QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=point + QPoint(-30, 30))
        moved = next(g for g in w.groups() if g['id'] == group_id)
        self.assertLess(moved['x'], old[0])
        self.assertGreater(moved['y'], old[1])
        canvas.setFocus()
        QTest.keyClick(canvas, Qt.Key_Z, Qt.ControlModifier)
        restored = next(g for g in w.groups() if g['id'] == group_id)
        self.assertEqual((restored['x'], restored['y']), old)

    def test_quick_changes_persist_and_switch_groups(self):
        w = self.window
        w.toggle_quick_settings()
        q = w.quick_settings
        q.group_box.setCurrentIndex(1)
        selected = w.selected_group()
        q.size_spin.setValue(23)
        q.font_box.setCurrentText("Lucida Console")
        q.style_box.setCurrentIndex(1)
        q.shadow.setChecked(False)
        saved = json.loads(wt_qt.CONFIG_PATH.read_text(encoding="utf-8"))
        group = next(g for g in saved["profiles"]["default"] if g["id"] == selected["id"])
        self.assertEqual((group["size"], group["font_family"], group["style"], group["shadow"]),
                         (23, "Lucida Console", "panel", False))
        self.assertEqual(w.font_box.currentText(), "Lucida Console")
        self.assertEqual(w.size_slider.value(), 23)

    def test_editing_drag_and_escape_restore_click_through(self):
        w = self.window
        w.show_hud()
        w.toggle_quick_settings()
        w.quick_settings.move_check.setChecked(True)
        view = w.overlays[0]
        self.assertFalse(view.windowFlags() & Qt.WindowTransparentForInput)
        old_x = view.group["x"]
        QTest.mousePress(view, Qt.LeftButton, pos=QPoint(5, 5))
        QTest.mouseMove(view, QPoint(-45, 30), delay=20)
        QTest.mouseRelease(view, Qt.LeftButton, pos=QPoint(5, 5))
        self.assertLess(view.group["x"], old_x)
        saved = json.loads(wt_qt.CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["profiles"]["default"][0]["x"], view.group["x"])
        QTest.keyClick(w.quick_settings, Qt.Key_Escape)
        self.assertFalse(w.quick_settings.isVisible())
        self.assertFalse(w.overlay_editing)
        self.assertTrue(view.windowFlags() & Qt.WindowTransparentForInput)

    @unittest.skipUnless(sys.platform == "win32", "Windows registration")
    def test_native_insert_and_rebinding_with_conflict(self):
        w = self.window
        if w.hotkey_error:
            self.skipTest("Insert is already registered by another Windows process")
        self.assertEqual(w.hotkey_error, "", "Close another running WT Flight instance before this test")
        w.hide()
        # Windows sends WM_HOTKEY to this process after the registered key is pressed.
        ctypes.windll.user32.keybd_event(0x2D, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x2D, 0, 2, 0)
        QTest.qWait(100)
        self.assertTrue(w.quick_settings.isVisible())
        self.assertFalse(w.isVisible())
        ctypes.windll.user32.keybd_event(0x2D, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x2D, 0, 2, 0)
        QTest.qWait(100)
        self.assertFalse(w.quick_settings.isVisible())
        w.toggle_quick_settings()
        w.quick_settings.key_edit.setKeySequence(QKeySequence("Ctrl+Shift+F9"))
        w.quick_settings.apply_hotkey()
        self.assertEqual(w.hotkey.sequence, "Ctrl+Shift+F9")
        self.assertEqual(wt_qt.Settings().data["menu_hotkey"], "Ctrl+Shift+F9")
        other = GlobalHotkey(lambda: None)
        try:
            ok, error = other.register("Ctrl+Shift+F10")
            self.assertTrue(ok, error)
            ok, error = w.hotkey.register("Ctrl+Shift+F10")
            self.assertFalse(ok)
            self.assertIn("занята", error)
            self.assertEqual(w.hotkey.sequence, "Ctrl+Shift+F9")
            self.assertFalse(w.hotkey.register("")[0])
            self.assertEqual(w.hotkey.sequence, "Ctrl+Shift+F9")
        finally:
            other.close()

    def test_migration_preserves_layout_and_short_labels(self):
        group = {"id": "old", "metrics": ["g"], "x": .3, "y": .6, "size": 18, "color": "#ffffff"}
        wt_qt.CONFIG_PATH.write_text(json.dumps({"version": 3, "profiles": {"default": [group]}}))
        settings = wt_qt.Settings()
        migrated = settings.groups("default")[0]
        self.assertEqual((migrated["x"], migrated["y"], migrated["color"]), (.3, .6, "#ffffff"))
        self.assertEqual(migrated["font_family"], "Consolas")
        view = wt_qt.GroupView(migrated, True)
        view.set_sample(("live", {"Ny": 3.5}, {}), {})
        self.assertEqual(view.lines()[0][:2], ("LDF", "+3.5 G"))
        self.assertEqual(view.hud_font().pixelSize(), 18)
        view.deleteLater()

    def test_catalog_search_categories_and_plus(self):
        w = self.window
        self.assertGreater(w.palette.topLevelItemCount(), 3)
        flight = w.palette.topLevelItem(0)
        self.assertTrue(flight.isExpanded())
        count = len(w.groups())
        w.palette.click_item(flight.child(0), 1)
        self.assertEqual(len(w.groups()), count + 1)
        self.assertEqual(w.groups()[-1]["metrics"], ["ias"])
        w.search.setText("CLMB")
        self.assertEqual(w.palette.topLevelItemCount(), 1)
        self.assertEqual(w.palette.topLevelItem(0).childCount(), 1)
        self.assertEqual(w.palette.topLevelItem(0).child(0).data(0, Qt.UserRole), "climb")
        w.search.setText("no such metric")
        self.assertEqual(w.metric_count.text(), "0")

    def test_delete_scope_and_editor_keyboard_tools(self):
        w = self.window
        w.show()
        w.activateWindow()
        w.canvas.setFocus()
        QTest.qWait(50)
        initial = len(w.groups())
        QTest.keyClick(w.canvas, Qt.Key_D, Qt.ControlModifier)
        self.assertEqual(len(w.groups()), initial + 1)
        duplicate = w.selected_group()
        x = duplicate["x"]
        QTest.keyClick(w.canvas, Qt.Key_Right, Qt.ShiftModifier)
        self.assertGreater(duplicate["x"], x)
        QTest.keyClick(w.canvas, Qt.Key_Delete)
        self.assertEqual(len(w.groups()), initial)
        engine = next(g for g in w.groups() if len(g["metrics"]) > 1)
        w.select_group(engine["id"])
        w.tabs.setCurrentIndex(1)
        w.text_details_button.setChecked(True)
        w.group_metrics.setCurrentRow(0)
        w.group_metrics.setFocus()
        before = len(engine["metrics"])
        QTest.keyClick(w.group_metrics, Qt.Key_Delete)
        self.assertEqual(len(engine["metrics"]), before - 1)
        w.title_edit.setText("AB")
        w.title_edit.setFocus()
        w.title_edit.setCursorPosition(0)
        QTest.keyClick(w.title_edit, Qt.Key_Delete)
        self.assertEqual(w.title_edit.text(), "B")
        self.assertEqual(len(w.groups()), initial)
        QTest.keyClick(w.title_edit, Qt.Key_F, Qt.ControlModifier)
        self.assertEqual(w.tabs.currentIndex(), 0)
        self.assertTrue(w.search.hasFocus())

    def test_themes_and_shared_hotkey_preferences(self):
        w = self.window
        if w.hotkey_error:
            self.skipTest("Insert is already registered by another Windows process")
        w.set_theme("arctic")
        self.assertEqual(wt_qt.Settings().data["theme"], "arctic")
        self.assertEqual(w.quick_settings.theme_box.currentData(), "arctic")
        w.quick_settings.theme_box.setCurrentIndex(w.quick_settings.theme_box.findData("cockpit"))
        self.assertEqual(wt_qt.Settings().data["theme"], "cockpit")
        self.assertTrue(w.theme_buttons["cockpit"].isChecked())
        original = w.hotkeys["hud"].sequence
        ok, message = w.apply_hotkey("hud", w.hotkeys["menu"].sequence)
        self.assertFalse(ok)
        self.assertEqual(w.hotkeys["hud"].sequence, original)
        self.assertTrue(w.apply_hotkey("hud", "")[0])
        self.assertIsNone(w.hotkeys["hud"].active_id)
        self.assertEqual(wt_qt.Settings().data["hotkeys"]["hud"], "")
        self.assertTrue(w.apply_hotkey("hud", "Ctrl+Shift+H")[0])
        self.assertEqual(w.main_key_panel.edits["hud"].keySequence().toString(), "Ctrl+Shift+H")
        self.assertEqual(w.quick_settings.key_panel.edits["hud"].keySequence().toString(), "Ctrl+Shift+H")

    @unittest.skipUnless(sys.platform == "win32", "Windows hotkeys")
    def test_multiple_native_actions_and_capture_does_not_trigger_action(self):
        w = self.window
        if w.hotkey_error:
            self.skipTest("Insert is already registered by another Windows process")
        self.assertTrue(all(not error for error in w.hotkey_errors.values()), w.hotkey_errors)
        self.assertEqual(len({binding.active_id for binding in w.hotkeys.values()}), 4)

        def chord(letter):
            user32 = ctypes.windll.user32
            for vk in (0x11, 0x10, ord(letter)):
                user32.keybd_event(vk, 0, 0, 0)
            for vk in (ord(letter), 0x10, 0x11):
                user32.keybd_event(vk, 0, 2, 0)
            QTest.qWait(70)

        w.hide()
        chord("H")
        self.assertTrue(w.hud_visible)
        chord("E")
        self.assertTrue(w.quick_settings.isVisible())
        self.assertTrue(w.overlay_editing)
        chord("E")
        self.assertFalse(w.overlay_editing)
        w.quick_settings.tabs.setCurrentIndex(2)
        w.quick_settings.key_panel.edits["move"].setFocus()
        QTest.qWait(20)
        chord("H")
        self.assertTrue(w.hud_visible, "Recording a registered key must not hide HUD")
        self.assertEqual(w.quick_settings.key_panel.edits["move"].keySequence().toString(), "Ctrl+Shift+H")
        capture = w.quick_settings.key_panel.edits["move"]
        QTest.keyClick(capture, Qt.Key_K, Qt.ControlModifier | Qt.AltModifier)
        self.assertEqual(capture.keySequence().toString(), "Ctrl+Alt+K")
        QTest.keyClick(capture, Qt.Key_Backspace)
        self.assertTrue(capture.keySequence().isEmpty())
        w.quick_settings.tabs.setCurrentIndex(0)
        w.quick_settings.visible_check.setFocus()
        chord("O")
        self.assertTrue(w.isVisible())
        self.assertFalse(w.quick_settings.isVisible())

    def test_background_copied_persisted_and_removed(self):
        w = self.window
        source = Path(self.temp.name) / "original.png"
        image = QImage(640, 360, QImage.Format_RGB32)
        image.fill(QColor("#234567"))
        image.save(str(source))
        self.assertTrue(w.load_background(str(source)))
        source.unlink()
        self.assertFalse(w.canvas.background.isNull())
        saved = wt_qt.Settings().data
        self.assertTrue(Path(saved["preview"]["image"]).exists())
        w.background_dim.setValue(35)
        self.assertEqual(wt_qt.Settings().data["preview"]["dimming"], 35)
        w.restore_background()
        self.assertFalse(w.canvas.background.isNull())
        self.assertEqual(w.canvas.dimming, 35)
        self.assertTrue(all(not hasattr(view, "background") for view in w.overlays))
        w.clear_background()
        self.assertTrue(w.canvas.background.isNull())
        self.assertEqual(wt_qt.Settings().data["preview"]["image"], "")
        w.restore_background()
        self.assertTrue(w.canvas.background.isNull(), "Clearing the image must not restore the default")

    def test_tooltip_is_readable_unscaled_and_tracks_the_row(self):
        w = self.window
        if os.getenv("QT_QPA_PLATFORM") == "offscreen":
            self.skipTest("Qt offscreen does not report tooltip font metrics reliably")
        w.show()
        w.move(100, 100)
        QTest.qWait(30)
        canvas = w.canvas
        canvas.set_screen_size(QSize(1920, 1080))
        group = w.groups()[0]
        group.update(x=.05, y=.05, metrics=["rpm", "flaps"])
        canvas.set_sample(w.sample, {})
        view = canvas.views[0]
        sizes = []
        for zoom in (0, .5, 1, 1.5):
            canvas.set_zoom(zoom)
            canvas.ensureVisible(view.graphicsProxyWidget())
            QTest.qWait(20)
            view.hover_pos = QPoint(5, 8)
            view.show_metric_tooltip()
            QTest.qWait(20)
            tip = view.metric_tip
            self.assertTrue(tip.isVisible())
            self.assertIsNone(tip.graphicsProxyWidget(), "Tooltip must never be embedded in the scaled scene")
            self.assertGreaterEqual(QFontInfo(tip.font()).pixelSize(), 15)
            self.assertEqual(tip.width(), 340)
            self.assertGreaterEqual(tip.height(), tip.heightForWidth(tip.width()))
            sizes.append(tip.size().toTuple())
            bounds = tip.screen().availableGeometry()
            self.assertTrue(bounds.contains(tip.geometry()))
            row_mid = 3 + view.fontMetrics().height() // 2
            anchor = canvas.viewport().mapToGlobal(canvas.mapFromScene(
                view.graphicsProxyWidget().mapToScene(QPointF(view.width(), row_mid))))
            self.assertLess(abs(tip.x() - anchor.x() - 12), 4)
            if os.getenv("WT_AUDIT_ARTIFACTS") and zoom == 0:
                folder = Path(os.environ["WT_AUDIT_ARTIFACTS"])
                folder.mkdir(parents=True, exist_ok=True)
                tip.grab().save(str(folder / "tooltip.png"))
                frame = w.grab()
                painter = QPainter(frame)
                painter.drawPixmap(tip.pos() - w.mapToGlobal(QPoint()), tip.grab())
                painter.end()
                frame.save(str(folder / "tooltip-in-editor.png"))
        self.assertTrue(all(size == sizes[0] for size in sizes), sizes)
        w.tabs.setCurrentIndex(1)
        QTest.qWait(20)
        self.assertFalse(tip.isVisible(), "Tooltip must close when leaving the canvas tab")

    def test_tooltip_persists_during_viewport_hover_and_hides_on_leave(self):
        if QApplication.platformName() != 'offscreen':
            self.skipTest('Run with QT_QPA_PLATFORM=offscreen to isolate hover from desktop cursor movement')
        w = self.window
        w.show()
        w.activateWindow()
        w.groups()[0].update(x=.1, y=.1)
        w.canvas.position_views()
        QTest.qWait(50)
        view = w.canvas.views[0]
        point = w.canvas.mapFromScene(view.graphicsProxyWidget().sceneBoundingRect().center())
        def hover(pos):
            viewport = w.canvas.viewport()
            # Deliver through the real viewport/scene path without depending on
            # which desktop window the OS currently allows to take foreground.
            QApplication.sendEvent(viewport, QMouseEvent(QEvent.MouseMove, QPointF(pos),
                QPointF(viewport.mapToGlobal(pos)), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        hover(point)
        QTest.qWait(700)
        self.assertTrue(view.metric_tip.isVisible())
        QTest.qWait(7000)
        self.assertTrue(view.metric_tip.isVisible(), "Description must not disappear on a timeout")
        hover(point + QPoint(120, 55))
        QTest.qWait(100)
        self.assertFalse(view.metric_tip.isVisible())

    def test_multiple_selection_moves_at_edge_and_deletes_as_one_undo(self):
        w = self.window
        canvas = w.canvas
        canvas.set_screen_size(QSize(1920, 1080))
        a, b = canvas.views[:2]
        a.group.update(x=.05, y=.15)
        b.group.update(x=.35, y=.35)
        canvas.position_views()
        canvas.set_selection({a.group['id'], b.group['id']}, a.group['id'])
        w.select_group(a.group['id'], preserve_selection=True)
        before_delta = b.pos() - a.pos()
        canvas.move_selected_by(b, -1000, -1000)
        self.assertEqual(b.pos() - a.pos(), before_delta)
        self.assertEqual(a.x(), 0)
        w.nudge_group(10, 10)
        self.assertEqual(b.pos() - a.pos(), before_delta)
        before = copy.deepcopy(w.groups())
        count = len(before)
        w.delete_group()
        self.assertEqual(len(w.groups()), count - 2)
        w.undo_layout()
        self.assertEqual(w.groups(), before)

    def test_font_changes_render_and_apply_to_selection(self):
        w = self.window
        if os.getenv("QT_QPA_PLATFORM") == "offscreen":
            self.skipTest("Qt offscreen does not report installed font families reliably")
        w.select_all_groups()
        w.font_box.setCurrentText("Consolas")
        view = w.canvas.views[0]
        first = view.grab().toImage()
        w.font_box.setCurrentText("Arial")
        self.assertTrue(all(g['font_family'] == 'Arial' for g in w.groups()))
        self.assertEqual(QFontInfo(view.hud_font()).family(), 'Arial')
        self.assertNotEqual(first, view.grab().toImage())
        w.hud_style_box.setCurrentIndex(w.hud_style_box.findData('war_thunder'))
        self.assertTrue(all(g['hud_style'] == 'war_thunder' for g in w.groups()))
        # Changing size in the quick menu must not overwrite other selected fonts.
        w.groups()[1]['font_family'] = 'Consolas'
        w.quick_settings.sync()
        w.quick_settings.size_spin.setValue(27)
        self.assertTrue(all(g['size'] == 27 for g in w.groups()))
        self.assertEqual(w.groups()[1]['font_family'], 'Consolas')

    def test_wheel_size_and_spin_buttons_without_accidental_font_changes(self):
        w = self.window
        w.show()
        w.activateWindow()
        w.select_all_groups()
        QTest.qWait(20)
        initial = [g['size'] for g in w.groups()]
        point = QPoint(100, 80)
        def wheel(widget, modifiers):
            event = QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)),
                                QPoint(), QPoint(0, 120), Qt.NoButton, modifiers,
                                Qt.NoScrollPhase, False)
            QApplication.sendEvent(widget, event)
        wheel(w.canvas.viewport(), Qt.ControlModifier)
        self.assertEqual([g['size'] for g in w.groups()], [size + 1 for size in initial])
        before_font = w.font_box.currentText()
        wheel(w.font_box, Qt.NoModifier)
        self.assertEqual(w.font_box.currentText(), before_font)
        value = w.size_slider.value()
        w.size_slider.up_button.click()
        self.assertEqual(w.size_slider.value(), value + 1)
        self.assertTrue(all(g['size'] == value + 1 for g in w.groups()))

    def test_custom_sound_survives_other_settings_and_sources_load(self):
        w = self.window
        self.assertIsNotNone(w.audio)
        source = str(w.audio.default_paths['speed'])
        with patch('wtflight.ui.feature_controls.QFileDialog.getOpenFileName', return_value=(source, '')):
            w.choose_warning_sound()
        paths = dict(w.settings.data['flight']['sound_files'])
        self.assertTrue(Path(paths['speed']).is_file())
        self.assertNotEqual(paths['speed'], source)
        w.volume_slider.setValue(42)
        w.repeat_spin.setValue(7)
        self.assertEqual(wt_qt.Settings().data['flight']['sound_files'], paths)
        self.assertTrue(w.audio.set_source('speed', paths['speed']))
        for _ in range(40):
            if all(effect.isLoaded() for effect in w.audio.effects.values()):
                break
            QTest.qWait(50)
        self.assertTrue(all(effect.isLoaded() for effect in w.audio.effects.values()))

    def test_compact_canvas_controls_do_not_overlap(self):
        w = self.window
        w.show()
        QTest.qWait(30)
        self.assertFalse(w.canvas_tools.isVisible())
        self.assertGreaterEqual(w.canvas.height(), 150)
        w.canvas_tools_action.setChecked(True)
        QTest.qWait(30)
        tools_bottom = w.canvas_tools.mapTo(w, QPoint(0, w.canvas_tools.height())).y()
        canvas_top = w.canvas.mapTo(w, QPoint()).y()
        self.assertLessEqual(tools_bottom, canvas_top)

    def test_fuel_warning_matches_color_at_exact_critical_threshold(self):
        sample = ('live', {'fuel_seconds': 60, '_fuel_minutes': 1}, {})
        self.assertEqual(wt_qt.warning_for(sample, {})[0], 'critical')

    def test_critical_speed_colors_both_label_and_value(self):
        view = wt_qt.GroupView(wt_qt.new_group('ias'), True)
        view.set_sample(('live', {'IAS, km/h': 1001}, {}), {'ias_kmh': 1000})
        with patch('wtflight.ui.main_window.time.monotonic', return_value=1.1):
            image = view.grab().toImage()
        split = wt_qt.QFontMetrics(view.hud_font()).horizontalAdvance('IAS') + 3
        def red_pixels(left, right):
            return sum(1 for x in range(left, right) for y in range(image.height())
                       if (lambda c: c.red() > 200 and c.green() < 150 and c.blue() < 160)(image.pixelColor(x, y)))
        self.assertGreater(red_pixels(0, split), 5)
        self.assertGreater(red_pixels(split, image.width()), 5)
        view.deleteLater()

    def test_alert_rows_flash_yellow_then_red_at_their_thresholds(self):
        self.assertEqual(wt_qt.alert_level(.89), '')
        self.assertEqual(wt_qt.alert_level(.9), 'caution')
        self.assertEqual(wt_qt.alert_level(1), 'critical')
        self.assertEqual(wt_qt.flashing_alert_color('caution', '#66d6a0', 1.1).name(), '#ffbd5a')
        self.assertEqual(wt_qt.flashing_alert_color('critical', '#66d6a0', 1.1).name(), '#ff6879')
        self.assertEqual(wt_qt.flashing_alert_color('critical', '#66d6a0', 1.2).name(), '#66d6a0')

    def test_all_presets_restore_and_export_roundtrip(self):
        w = self.window
        from wtflight.core._features import validate_profile
        self.assertEqual([w.preset_box.itemData(index)[1] for index in range(w.preset_box.count())],
                         ["combat", "engine", "helicopter", "empty"])
        for index in range(w.preset_box.count()):
            w.main_preset_box.setCurrentIndex(index)
            self.assertEqual(w.preset_box.currentData(), w.main_preset_box.currentData())
            w.apply_main_preset_button.click()
            original = [g['metrics'] for g in w.groups()]
            if w.groups():
                w.groups()[0]['metrics'] = ['warning']
            w.restore_standard_preset()
            self.assertEqual([g['metrics'] for g in w.groups()], original)
            exported = {'format': 'wt-flight-profile', 'version': 1, 'groups': w.groups()}
            restored = validate_profile(json.loads(json.dumps(exported)))
            self.assertEqual([g['metrics'] for g in restored], original)

    def test_detected_aircraft_limits_and_unknown_switch(self):
        w = self.window
        state = {"valid": True, "IAS, km/h": 1450, "Ny": 3, "Mfuel, kg": 3000}
        w.on_sample("live", state, {"type": "f_16c_block_50"})
        self.assertEqual(w.current_limits()["ias_kmh"], 1555)
        self.assertIn("limit_pos_g", w.available)
        self.assertEqual(wt_qt.warning_for(w.sample, w.current_limits())[0], "caution")
        w.settings.data["limits"][w.aircraft] = {"ias_kmh": 1300}
        self.assertEqual(w.current_limits()["ias_kmh"], 1300)
        self.assertEqual(wt_qt.warning_for(w.sample, w.current_limits())[0], "critical")
        w.on_sample("live", state, {"type": "unknown_plane"})
        self.assertEqual(w.current_limits(), {})
        self.assertNotIn("limit_ias", w.available)
        w.on_sample("live", state, {})
        self.assertEqual(w.aircraft, "default")
        self.assertEqual(w.current_limits(), {})


if __name__ == "__main__":
    unittest.main()
