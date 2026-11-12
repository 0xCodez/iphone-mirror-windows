import asyncio
import socket
import threading
import time
import unittest

from iphone_mirror.airplay import Connection, Receiver
from iphone_mirror.video import MirrorStream, VideoDecoder


class _Rx:
    def release_mirror(self, _conn):
        return None

    def emit(self, _event, **_info):
        return None


class StopTests(unittest.TestCase):
    def test_stop_closes_the_mirror_socket_before_it_returns(self):
        """Switching pictures must drop the phone's video connection.

        Stopping the listen loop without closing that socket leaves the last
        frame on screen and blocks the next Screen Mirroring session.
        """
        loop = asyncio.new_event_loop()
        ready = threading.Event()
        holder = {}

        async def setup():
            dec = VideoDecoder(lambda *_a: None)
            stream = MirrorStream(b"k" * 16, 1, dec, lambda *_a, **_k: None)
            holder["stream"] = stream
            holder["port"] = await stream.start()
            ready.set()

        def run():
            asyncio.set_event_loop(loop)
            loop.create_task(setup())
            loop.run_forever()

        thread = threading.Thread(target=run, name="airplay-stop-test", daemon=True)
        thread.start()
        self.assertTrue(ready.wait(3), "mirror server did not start")
        client = socket.create_connection(("127.0.0.1", holder["port"]), timeout=2)
        self.addCleanup(client.close)
        deadline = time.monotonic() + 2
        while holder["stream"]._task is None:
            if time.monotonic() > deadline:
                self.fail("mirror handler did not start")
            time.sleep(0.01)

        owner = type("Owner", (), {})()
        owner.audio = None
        owner.mirror = holder["stream"]
        owner.timing = None
        owner.writer = type("Writer", (), {"close": lambda self: None})()
        owner.rx = _Rx()

        async def cleanup():
            await Connection.cleanup(owner)

        owner.cleanup = cleanup

        harness = type("Harness", (), {})()
        harness._did_stop = False
        harness.advertiser = None
        harness.player = None
        harness.decoder = VideoDecoder(lambda *_a: None)
        harness.loop = loop
        harness._server = None
        harness._thread = thread
        harness._mirror_owner = owner

        Receiver.stop(harness)

        client.setblocking(False)
        data = None
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                data = client.recv(16)
                break
            except BlockingIOError:
                time.sleep(0.02)
            except ConnectionResetError:
                data = b""
                break
        self.assertEqual(data, b"")
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
