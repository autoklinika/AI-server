"""No socket connection: observer evidence loss and hostile responses fail closed."""
import importlib.util
from pathlib import Path
import socket
import struct
import unittest
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('observer_disconnect',ROOT /
    'src/ai_bridge/gateway/vision_gpu_observer_client.py')
client=importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class ObserverDisconnect(unittest.TestCase):
    def connection(self):
        conn=MagicMock()
        conn.getsockopt.return_value=struct.pack('3i',50,0,0)
        factory=MagicMock()
        factory.return_value.__enter__.return_value=conn
        return factory,conn

    def test_timeout_restart_eof_and_corrupt_reply_never_mean_empty(self):
        for reply in (TimeoutError('mock'),ConnectionResetError('mock'),b'',b'garbage\n',
                      b'{"schema_version":1,"status":"evidence_unavailable"}\n'):
            factory,conn=self.connection()
            conn.recv.side_effect=[reply]
            with patch.object(client.socket,'socket',factory):
                self.assertIsNone(client.snapshot_observer(socket_path=Path('/mock/observer.sock')))

    def test_wrong_server_uid_denied_before_request(self):
        factory,conn=self.connection()
        conn.getsockopt.return_value=struct.pack('3i',50,994,994)
        with patch.object(client.socket,'socket',factory):
            self.assertIsNone(client.snapshot_observer(socket_path=Path('/mock/observer.sock')))
        conn.sendall.assert_not_called()

    def test_pid_birth_reuse_reply_denied(self):
        factory,conn=self.connection()
        conn.recv.return_value=(b'{"schema_version":1,"status":"ok","worker":'
                               b'{"pid":50,"birth":61,"uid":994,"exe":"/mock/python"}}\n')
        with patch.object(client.socket,'socket',factory):
            self.assertIsNone(client.inspect_worker_observer(socket_path=Path('/mock/observer.sock'),
                              pid=50,birth=60,worker_uid=994))


if __name__=='__main__':
    unittest.main()
