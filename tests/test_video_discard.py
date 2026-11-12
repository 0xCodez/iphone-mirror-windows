import queue
import unittest

from iphone_mirror.video import VideoDecoder


class DiscardTests(unittest.TestCase):
    def test_discard_drops_a_queued_packet_and_retires_its_epoch(self):
        dec = VideoDecoder(lambda *_a: None)
        dec.q.put_nowait(b"old")
        taken = dec._epoch
        dec.discard()
        self.assertTrue(dec.q.empty())
        self.assertNotEqual(taken, dec._epoch)

    def test_a_packet_taken_before_discard_is_stale(self):
        dec = VideoDecoder(lambda *_a: None)
        epoch = dec._epoch
        dec.discard()
        self.assertNotEqual(epoch, dec._epoch)
        self.assertIsInstance(dec.q, queue.Queue)


if __name__ == "__main__":
    unittest.main()
