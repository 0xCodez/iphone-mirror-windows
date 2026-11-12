import unittest

from iphone_mirror.ui import background_wifi_is_live, controls_are_pending, keep_wifi_in_background


class PictureSwitchTests(unittest.TestCase):
    def test_cable_keeps_a_live_wifi_picture(self):
        self.assertTrue(keep_wifi_in_background("cable", True, True))

    def test_cable_does_not_keep_a_picture_that_is_not_up(self):
        self.assertFalse(keep_wifi_in_background("cable", True, False))

    def test_wifi_does_not_park_itself(self):
        self.assertFalse(keep_wifi_in_background("wifi", True, True))

    def test_the_bar_waits_until_clicks_work(self):
        self.assertTrue(controls_are_pending(True, False, True, False))
        self.assertFalse(controls_are_pending(True, False, True, True))
        self.assertFalse(controls_are_pending(False, False, True, False))
        self.assertFalse(controls_are_pending(True, True, True, False))

    def test_a_recent_frame_is_still_live(self):
        self.assertTrue(background_wifi_is_live(0.2))
        self.assertFalse(background_wifi_is_live(2.0))
        self.assertFalse(background_wifi_is_live(None))


if __name__ == "__main__":
    unittest.main()
