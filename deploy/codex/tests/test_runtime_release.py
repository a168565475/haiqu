"""仅内存归档及命令替身；不访问服务器、账号或 Docker。"""
import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import MagicMock, Mock, patch
import zipfile

import runtime_release_bundle as bundle


def wheel(package, version):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(f'{package}-{version}.dist-info/METADATA', f'Name: {package}\nVersion: {version}\n')
    return output.getvalue()


def fixture_content():
    content = {name: b'public source' for name in bundle.SOURCE_FILES}
    wheels = {'ezdxf-1.4.5-py3-none-any.whl': wheel('ezdxf', '1.4.5'),
              'shapely-2.2.0-cp313-cp313-manylinux_2_28_x86_64.whl': wheel('Shapely', '2.2.0')}
    content.update({'vendor/wheels/' + name: data for name, data in wheels.items()})
    content['vendor/requirements.lock'] = bundle.locked_requirements(wheels)
    return content


def packet(content, mutate_manifest=None, extra_member=None):
    manifest = {'schema_version': 1, 'task': bundle.TASK, 'scope': bundle.SCOPE,
                'files': {name: bundle.describe(data) for name, data in content.items()}}
    if mutate_manifest:
        mutate_manifest(manifest)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name, data in {**content, 'release_manifest.json': bundle.canonical(manifest)}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        if extra_member:
            archive.addfile(extra_member)
    return output.getvalue()


class BundleTests(unittest.TestCase):
    def test_valid_fixed_source_and_hash_locked_wheels(self):
        content = fixture_content()
        raw = packet(content)
        self.assertEqual(bundle.validate_bundle(raw, bundle.sha(raw))[0], content)

    def test_traversal_extra_paths_missing_source_and_hash_drift_rejected(self):
        original = fixture_content()
        for content in ({**original, '../auth.json': b'no'}, {**original, 'data/customer.dxf': b'no'},
                        {name: data for name, data in original.items() if name != 'src/codex_runtime/service.py'}):
            raw = packet(content)
            with self.assertRaises(bundle.ReleaseError):
                bundle.validate_bundle(raw, bundle.sha(raw))
        raw = packet(original, lambda value: value['files']['src/codex_runtime/service.py'].update(sha256='0' * 64))
        with self.assertRaisesRegex(bundle.ReleaseError, 'SOURCE_HASH'):
            bundle.validate_bundle(raw, bundle.sha(raw))

    def test_symlink_duplicate_and_wrong_bundle_hash_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.REGTYPE):
            info = tarfile.TarInfo('src/codex_runtime/service.py')
            info.type = kind
            raw = packet(fixture_content(), extra_member=info)
            with self.assertRaises(bundle.ReleaseError):
                bundle.validate_bundle(raw, bundle.sha(raw))
        raw = packet(fixture_content())
        with self.assertRaisesRegex(bundle.ReleaseError, 'BUNDLE_HASH'):
            bundle.validate_bundle(raw, '0' * 64)

    def test_wrong_core_version_platform_and_modified_lock_rejected(self):
        for name, data in (('ezdxf-1.4.5-cp313-cp313-win_amd64.whl', wheel('ezdxf', '1.4.5')),
                           ('ezdxf-1.4.4-py3-none-any.whl', wheel('ezdxf', '1.4.4'))):
            wheels = {name: data, 'shapely-2.2.0-py3-none-any.whl': wheel('Shapely', '2.2.0')}
            with self.assertRaises(bundle.ReleaseError):
                bundle.locked_requirements(wheels)
        content = fixture_content()
        content['vendor/requirements.lock'] = b'ezdxf\n'
        raw = packet(content)
        with self.assertRaisesRegex(bundle.ReleaseError, 'WHEEL_LOCK'):
            bundle.validate_bundle(raw, bundle.sha(raw))


class UpgradeTests(unittest.TestCase):
    def test_running_operation_blocks_switch(self):
        from server_runtime_upgrade import require_idle
        for status in ('RUNNING', 'UNKNOWN'):
            with self.assertRaises(bundle.ReleaseError):
                require_idle({'cli_version': '0.165.0', 'operation': {'state': status}})
        require_idle({'cli_version': '0.165.0', 'operation': {'state': 'SUCCEEDED'}})

    def test_target_names_and_container_identity_are_exact(self):
        from server_runtime_upgrade import require_target_identity, NAME, OWNER_TASK
        value = {'Name': '/' + NAME, 'Id': 'a' * 64,
                 'Config': {'Labels': {'task': OWNER_TASK, 'scope': 'runtime-local-erp', 'bundle_sha256': 'b' * 64}}}
        require_target_identity(value, NAME)
        for change in ({'Name': '/haiqu-backend'}, {'Id': 'bad'}, {'Config': {'Labels': {'task': 'another-task'}}}):
            with self.assertRaises(bundle.ReleaseError):
                require_target_identity({**value, **change}, NAME)

    def test_failed_new_start_recovers_exact_prior_container(self):
        import server_runtime_upgrade as upgrade
        previous = {'container_id': 'a' * 64, 'image_id': 'sha256:' + 'b' * 64}
        receipt = {'previous': previous, 'new_container_id': 'c' * 64, 'bundle_sha256': 'd' * 64,
                   'image_id': 'sha256:' + 'f' * 64, 'previous_name': upgrade.NAME + '-before-' + 'd' * 12}
        old = {'Id': previous['container_id'], 'Image': previous['image_id'], 'Name': '/' + receipt['previous_name']}
        new = {'Id': receipt['new_container_id'], 'Image': receipt['image_id'], 'Name': '/' + upgrade.NAME,
               'Config': {'Labels': {'bundle_sha256': receipt['bundle_sha256'], 'task': upgrade.OWNER_TASK, 'scope': bundle.SCOPE}}}
        with patch.object(upgrade, 'container', side_effect=[old, new]), patch.object(upgrade, 'absent', return_value=False), patch.object(upgrade, 'command') as command, \
                patch.object(upgrade, 'wait_ready') as wait:
            upgrade.restore_previous(receipt)
        calls = [call.args[0] for call in command.call_args_list]
        self.assertEqual(calls, [['docker', 'stop', '--time', '115', receipt['new_container_id']],
                                ['docker', 'rm', receipt['new_container_id']],
                                ['docker', 'rename', previous['container_id'], upgrade.NAME],
                                ['docker', 'start', previous['container_id']]])
        wait.assert_called_once_with(previous['container_id'], capability=False)

    def test_rollback_refuses_foreign_new_or_previous_identity(self):
        import server_runtime_upgrade as upgrade
        receipt = {'previous': {'container_id': 'a' * 64, 'image_id': 'sha256:' + 'b' * 64},
                   'new_container_id': 'c' * 64, 'bundle_sha256': 'd' * 64,
                   'previous_name': upgrade.NAME + '-before-' + 'd' * 12}
        with patch.object(upgrade, 'container', return_value={'Id': 'e' * 64}), patch.object(upgrade, 'command') as command:
            with self.assertRaises(bundle.ReleaseError):
                upgrade.restore_previous(receipt)
            command.assert_not_called()

    def test_interrupted_before_rename_only_restarts_original_id(self):
        import server_runtime_upgrade as upgrade
        receipt = {'previous': {'container_id': 'a' * 64, 'image_id': 'sha256:' + 'b' * 64},
                   'previous_name': upgrade.NAME + '-before-' + 'd' * 12}
        old = {'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64, 'Name': '/' + upgrade.NAME}
        with patch.object(upgrade, 'container', return_value=old), patch.object(upgrade, 'command') as command, \
                patch.object(upgrade, 'wait_ready'):
            upgrade.restore_previous(receipt)
        command.assert_called_once_with(['docker', 'start', 'a' * 64])

    def test_activated_but_dead_new_container_can_roll_back(self):
        import server_runtime_upgrade as upgrade
        receipt = {'status': 'ACTIVATED', 'bundle_sha256': 'd' * 64, 'new_container_id': 'c' * 64,
                   'image_id': 'sha256:' + 'f' * 64, 'previous': {'container_id': 'a' * 64}}
        path = MagicMock()
        paths = {name: Mock() for name in ('activation.json', 'rollback.json', 'rollback-started.json')}
        paths['activation.json'].exists.return_value = True
        paths['rollback.json'].exists.return_value = False
        paths['rollback-started.json'].exists.return_value = False
        path.__truediv__.side_effect = paths.__getitem__
        current = {'Id': receipt['new_container_id'], 'Image': receipt['image_id'], 'Name': '/' + upgrade.NAME,
                   'State': {'Running': False}, 'Config': {'Labels': {'bundle_sha256': receipt['bundle_sha256'],
                   'task': upgrade.OWNER_TASK, 'scope': bundle.SCOPE}}}
        with patch.object(upgrade, 'read_record', return_value=receipt), patch.object(upgrade, 'container', return_value=current), \
                patch.object(upgrade, 'status') as status, patch.object(upgrade, 'restore_previous') as restore, \
                patch.object(upgrade, 'save_new'):
            result = upgrade.rollback(path, receipt['bundle_sha256'])
        self.assertEqual(result['status'], 'ROLLED_BACK')
        status.assert_not_called()
        restore.assert_called_once_with(receipt)

    def test_rollback_reenters_after_new_removal_or_old_rename(self):
        import server_runtime_upgrade as upgrade
        receipt = {'status': 'ACTIVATED', 'bundle_sha256': 'd' * 64, 'new_container_id': 'c' * 64,
                   'image_id': 'sha256:' + 'f' * 64, 'previous_name': upgrade.NAME + '-before-' + 'd' * 12,
                   'previous': {'container_id': 'a' * 64, 'image_id': 'sha256:' + 'b' * 64}}
        for name in (receipt['previous_name'], upgrade.NAME):
            path = MagicMock()
            paths = {key: Mock() for key in ('activation.json', 'rollback.json', 'rollback-started.json')}
            for key, value in paths.items():
                value.exists.return_value = key != 'rollback.json'
            path.__truediv__.side_effect = paths.__getitem__
            old = {'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64, 'Name': '/' + name}
            with self.subTest(stage=name), patch.object(upgrade, 'read_record', return_value=receipt), \
                    patch.object(upgrade, 'container', return_value=old), patch.object(upgrade, 'absent', return_value=True), \
                    patch.object(upgrade, 'status') as status, patch.object(upgrade, 'command') as command, \
                    patch.object(upgrade, 'wait_ready'), patch.object(upgrade, 'save_new'):
                self.assertEqual(upgrade.rollback(path, receipt['bundle_sha256'])['status'], 'ROLLED_BACK')
            status.assert_not_called()
            expected = [] if name == upgrade.NAME else [['docker', 'rename', 'a' * 64, upgrade.NAME]]
            self.assertEqual([call.args[0] for call in command.call_args_list], expected + [['docker', 'start', 'a' * 64]])


if __name__ == '__main__':
    unittest.main()
