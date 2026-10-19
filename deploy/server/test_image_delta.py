"""镜像增量工具的隔离文件测试；不调用 Docker、不访问网络。"""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import unittest


PROJECT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).with_name('image_delta.py')
TEMP = PROJECT / 'qa/.image_delta_unit_temp'


class ImageDeltaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEMP.mkdir(exist_ok=False)

    @classmethod
    def tearDownClass(cls):
        TEMP.rmdir()

    def setUp(self):
        self.work = TEMP / self._testMethodName
        self.work.mkdir(exist_ok=False)

    def tearDown(self):
        self.assertEqual(self.work.resolve().parent, TEMP.resolve())
        shutil.rmtree(self.work)

    def command(self, *args, good=True):
        result = subprocess.run([sys.executable, '-B', str(TOOL), *map(str, args)],
                                capture_output=True, text=True)
        self.assertNotIn("can't open file", result.stderr, '工具尚未实现')
        if good:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def archive(self, name, layer=b'shared', mutate=None):
        files = {}
        def blob(data, media):
            digest = hashlib.sha256(data).hexdigest()
            files['blobs/sha256/' + digest] = data
            return {'mediaType': media, 'digest': 'sha256:' + digest, 'size': len(data)}
        config = blob(b'{"architecture":"amd64","os":"linux"}', 'application/vnd.oci.image.config.v1+json')
        layers = [blob(b'shared', 'application/vnd.oci.image.layer.v1.tar')]
        if layer != b'shared':
            layers.append(blob(layer, 'application/vnd.oci.image.layer.v1.tar'))
        docker_layers = ['blobs/sha256/' + item['digest'][7:] for item in layers]
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'config': config, 'layers': layers}
        if mutate:
            mutate(manifest, files)
        target = blob(json.dumps(manifest).encode(), manifest['mediaType'])
        files['index.json'] = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [target]}).encode()
        files['oci-layout'] = b'{"imageLayoutVersion":"1.0.0"}'
        files['manifest.json'] = json.dumps([{'Config': 'blobs/sha256/' + config['digest'][7:], 'RepoTags': ['delta:test'], 'Layers': docker_layers}]).encode()
        path = self.work / name
        self.write_tar(path, files)
        return path

    def write_tar(self, path, files, extra=None):
        with tarfile.open(path, 'w') as archive:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            if extra:
                archive.addfile(extra, io.BytesIO(b'') if extra.isfile() else None)

    def setup_delta(self):
        base = self.archive('base.tar')
        source = self.archive('source.tar', b'new-layer')
        index, delta, recipe, rebuilt = [self.work / name for name in ('base.json', 'delta.tar', 'recipe.json', 'rebuilt.tar')]
        self.command('inventory', base, '--output', index)
        summary = self.command('delta', source, '--baseline', index, '--output', delta, '--recipe', recipe)
        return base, source, delta, recipe, rebuilt, summary

    def test_roundtrip_reuses_blobs_and_verifies_every_file(self):
        base, source, delta, recipe, rebuilt, summary = self.setup_delta()
        self.assertEqual(summary['reused_blob_count'], 2)
        self.assertIn('index.json', summary['included'])
        self.command('reassemble', base, '--delta', delta, '--recipe', recipe, '--output', rebuilt)
        verified = self.command('verify', rebuilt, '--recipe', recipe)
        inventory = self.command('inventory', source)
        self.assertEqual(verified['files'], inventory['files'])
        self.assertEqual(verified['format'], 'OCI')

    def test_rejects_illegal_paths(self):
        for position, name in enumerate(('../escape', '/absolute', r'blobs\sha256\bad', './index.json')):
            path = self.work / f'bad{position}.tar'
            self.write_tar(path, {name: b''})
            self.command('inventory', path, good=False)

    def test_rejects_duplicate_and_link_members(self):
        for position, kind in enumerate((tarfile.REGTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE)):
            member = tarfile.TarInfo('index.json' if kind == tarfile.REGTYPE else 'oci-layout')
            member.type = kind
            member.linkname = '/outside'
            path = self.work / f'bad{position}.tar'
            self.write_tar(path, {'index.json': b'{}'}, member)
            result = self.command('inventory', path, good=False)
            self.assertIn('Duplicate archive' if kind == tarfile.REGTYPE else 'Forbidden member type', result.stderr)

    def test_rejects_blob_digest_mismatch(self):
        path = self.work / 'bad.tar'
        self.write_tar(path, {'blobs/sha256/' + '0' * 64: b'corrupt'})
        self.command('inventory', path, good=False)

    def test_rejects_missing_blob_and_wrong_descriptor_size(self):
        for name, mutate in (
            ('missing', lambda m, f: f.pop('blobs/sha256/' + m['layers'][0]['digest'][7:])),
            ('size', lambda m, f: m['layers'][0].update(size=999)),
            ('nodigest', lambda m, f: m['layers'][0].pop('digest')),
            ('nosize', lambda m, f: m['layers'][0].pop('size')),
        ):
            self.command('verify', self.archive(name + '.tar', mutate=mutate), good=False)

    def test_wrong_baseline_cannot_leave_partial_output(self):
        base, source, delta, recipe, rebuilt, summary = self.setup_delta()
        wrong = self.archive('wrong.tar', mutate=lambda m, f: f.pop('blobs/sha256/' + m['layers'][0]['digest'][7:]))
        self.command('reassemble', wrong, '--delta', delta, '--recipe', recipe, '--output', rebuilt, good=False)
        self.assertFalse(rebuilt.exists())

    def test_tampered_delta_and_recipe_are_rejected(self):
        base, source, delta, recipe, rebuilt, summary = self.setup_delta()
        content = bytearray(delta.read_bytes())
        content[1024] ^= 1
        delta.write_bytes(content)
        self.command('reassemble', base, '--delta', delta, '--recipe', recipe, '--output', rebuilt, good=False)
        self.assertFalse(rebuilt.exists())
        plan = json.loads(recipe.read_text())
        plan['files'][0]['name'] = '../escape'
        recipe.write_text(json.dumps(plan))
        self.command('verify', source, '--recipe', recipe, good=False)

    def test_output_existing_file_is_never_overwritten(self):
        path = self.archive('source.tar')
        output = self.work / 'existing.json'
        output.write_bytes(b'keep')
        self.command('inventory', path, '--output', output, good=False)
        self.assertEqual(output.read_bytes(), b'keep')

    def test_incomplete_baseline_index_is_rejected(self):
        source = self.archive('source.tar')
        baseline = self.work / 'baseline.json'
        baseline.write_text(json.dumps({'format': 'OCI', 'files': [{'name': 'index.json', 'bytes': 1}]}))
        delta, recipe = self.work / 'delta.tar', self.work / 'recipe.json'
        self.command('delta', source, '--baseline', baseline, '--output', delta, '--recipe', recipe, good=False)
        self.assertFalse(delta.exists())
        self.assertFalse(recipe.exists())

    def test_recipe_write_failure_removes_own_partial_delta(self):
        base = self.archive('base.tar')
        baseline, delta = self.work / 'base.json', self.work / 'delta.tar'
        self.command('inventory', base, '--output', baseline)
        self.command('delta', base, '--baseline', baseline, '--output', delta,
                     '--recipe', self.work / 'missing/recipe.json', good=False)
        self.assertFalse(delta.exists())


if __name__ == '__main__':
    unittest.main()
