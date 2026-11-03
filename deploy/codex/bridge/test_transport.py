"""技术单测：帧边界与stdin断开回收，不连接ERP API、数据库或模型。"""
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
import unittest

import transport


class FrameTests(unittest.TestCase):
    def test_fragmented_frame(self):
        payload = '中文'.encode()
        packet = struct.pack('!I', len(payload)) + payload
        left, right = socket.socketpair()
        try:
            for byte in packet:
                left.sendall(bytes([byte]))
            self.assertEqual(transport.frame(right), packet)
        finally:
            left.close()
            right.close()

    def test_invalid_lengths(self):
        for count in (0, transport.MAX_FRAME + 1):
            left, right = socket.socketpair()
            try:
                left.sendall(struct.pack('!I', count))
                with self.assertRaisesRegex(RuntimeError, 'FRAME_LIMIT'):
                    transport.frame(right)
            finally:
                left.close()
                right.close()

    def test_truncated_frame(self):
        left, right = socket.socketpair()
        try:
            left.sendall(struct.pack('!I', 4) + b'a')
            left.shutdown(socket.SHUT_WR)
            with self.assertRaises(EOFError):
                transport.frame(right)
        finally:
            left.close()
            right.close()

    def test_bounded_large_write(self):
        left, right = socket.socketpair()
        payload = b'x' * 200000
        packet = struct.pack('!I', len(payload)) + payload
        received = []
        reader = threading.Thread(target=lambda: received.append(transport.frame(right)))
        try:
            reader.start()
            transport.send(left, packet)
            reader.join(7)
            self.assertFalse(reader.is_alive())
            self.assertEqual(received, [packet])
        finally:
            left.close()
            right.close()
            reader.join(1)


class LifecycleTests(unittest.TestCase):
    def test_idle_stdin_eof_removes_socket(self):
        # 路径已登记；拒绝复用任何原有目录，子进程关闭后只移除本目录。
        directory = Path('/tmp/haiqu-codex-bridge-technical-20261103-a1')
        self.assertFalse(os.path.lexists(directory))
        directory.mkdir(mode=0o750)
        os.chown(directory, 10001, 10001)
        path = directory / 'runtime.sock'
        process = None
        try:
            source = transport.SOURCE_FOR_TEST
            script = "ns={'__name__':'transport_unit'};exec(" + repr(source) + ",ns);"
            script += "ns['LOCAL_SOCKET']=ns['Path'](" + repr(str(path)) + ");ns['local']()"
            def identity():
                os.setgid(10001)
                os.setuid(10001)
            process = subprocess.Popen([sys.executable, '-I', '-B', '-u', '-c', script],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=identity)
            deadline = time.monotonic() + 5
            while not path.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(path.exists(), process.stderr.read(512) if process.poll() is not None else b'not ready')
            process.stdin.close()
            self.assertEqual(process.wait(5), 0)
            self.assertFalse(os.path.lexists(path))
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    process.wait(5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
            # 清理失败保留现场、让测试失败，不能递归删除未知文件。
            lock = directory / 'bridge.lock'
            if os.path.lexists(lock):
                info = lock.lstat()
                self.assertTrue(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                                and info.st_uid == 10001 and stat.S_IMODE(info.st_mode) == 0o600)
                lock.unlink()
            directory.rmdir()


if __name__ == '__main__':
    unittest.main()
