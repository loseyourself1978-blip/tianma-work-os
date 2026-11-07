"""Release media integrity check. No network, model calls or file mutation."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import struct


class Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.links = []
        self.link_text = []
        self.current_link = None
    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            self.images.append(dict(attrs))
        if tag == 'a':
            self.current_link = dict(attrs)
            self.current_link['text'] = ''
            self.links.append(self.current_link)
    def handle_data(self, data):
        if self.current_link is not None:
            self.current_link['text'] += data
    def handle_endtag(self, tag):
        if tag == 'a':
            self.current_link = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--interface-version', required=True)
    parser.add_argument('--interface-build', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    m = json.loads((root / 'assets/product/media-manifest.json').read_text())
    interface = m['interface']
    assert interface['version'] == args.interface_version, 'Stale interface version'
    assert interface['build'] == args.interface_build, 'Stale interface build'
    assert interface['kind'] == 'REAL_MACOS_WINDOW_CAPTURE'
    assert interface['privacy_review']
    outfits = m['nyra']['outfits']
    assert {x['id'] for x in outfits} == {
        'runtime-default', 'runtime-office', 'runtime-gala',
        'runtime-office_white', 'runtime-gala_red'}, 'Five runtime outfits required'
    html = (root / 'index.html').read_text()
    document = Images()
    document.feed(html)
    images = {x['src'].removeprefix('./'): x for x in document.images}
    assert len(images) == len(document.images), 'Duplicate media entry'
    combinations = m.get('combinations', [])
    assert {x['id'] for x in combinations} >= {
        'chatgpt-deepseek', 'chatgpt-claude', 'deepseek-codex', 'claude-codex'
    }, 'Required real service combinations missing'
    for item in combinations:
        assert item['kind'] == 'REAL_MACOS_WINDOW_CAPTURE'
        assert item['version'] == interface['version'] and item['build'] == interface['build']
        assert item['source_commit'] == interface['source_commit']
        assert item['privacy_review'] and item['state']
    for item in [interface] + outfits + combinations:
        path = (root / item['path']).resolve()
        assert path.is_relative_to(root) and path.is_file()
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['sha256'], item['path']
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', data[16:24]) == (item['width'], item['height'])
        image = images[item['path']]
        assert image.get('alt') and int(image['width']) == item['width']
        assert int(image['height']) == item['height']
    assert interface['version'] in html and interface['build'] in html
    assert '/releases/tag/v' + m['public_download_version'] in html
    if interface['status'] == 'CANDIDATE_PREVIEW':
        assert 'candidate preview' in html.lower() and 'not yet a public release' in html
    else:
        release = json.loads((root.parent / 'docs/release-1.0/release.json').read_text())
        assert release['version'] == m['public_download_version'] == interface['version']
        assert release['build'] == m['public_download_build'] == interface['build']
        assert release['source_commit'] == interface['source_commit']
        assert release['sha256'] == m['public_artifact_sha256']
        assert release['github_release'] == m['public_download_url']
        downloads = [x for x in document.links if x['text'].strip().startswith('Download TWOS ')]
        assert len(downloads) == 1, 'Expected exactly one primary download button'
        assert downloads[0]['text'].strip() == 'Download TWOS ' + release['version']
        assert downloads[0]['href'] == release['github_release'], 'Stale download destination'
        assert 'Current public DMG: ' + release['version'] + ' · build ' + release['build'] in html
        assert m['nyra']['source_commit'] == release['embedded_nyra_source_commit']
        assert m['nyra']['version'] == release['embedded_nyra_version']
        assert m['nyra']['build'] == release['embedded_nyra_build']
    print(json.dumps({'result': 'STATIC_PASS', 'interface': args.interface_version,
                      'build': args.interface_build, 'outfits': len(outfits),
                      'images': len(images), 'combinations': len(combinations), 'gui_verified': False}))


if __name__ == '__main__':
    main()
