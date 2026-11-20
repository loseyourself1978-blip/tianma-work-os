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
        self.videos = []
        self.sources = []
        self.links = []
        self.link_text = []
        self.current_link = None
    def handle_starttag(self, tag, attrs):
        if tag == 'video':
            self.videos.append(dict(attrs))
        if tag == 'source':
            self.sources.append(dict(attrs))
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
    team = m.get('ai_team', [])
    if tuple(int(v) for v in interface['version'].split('.')) >= (1, 0, 12):
        assert team, 'Current AI Team setup and saved group screenshots required'
    if team:
        assert [x['id'] for x in team] == ['team-setup', 'team-group']
        for item in team:
            assert all(item[k] == interface[k] for k in ['version', 'build', 'source_commit'])
            assert item['privacy_review']
        assert team[1]['kind'] == 'REAL_MACOS_WINDOW_DETAIL' and team[1]['state'] == 'READONLY_SYNTHETIC_HISTORY'
    for item in [interface] + outfits + combinations + team:
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
    if 'demo' in m:
        demo = m['demo']
        versions = demo['versions']
        assert [v['narration'] for v in versions] == ['en-US', 'zh-CN']
        assert len(document.videos) == len(document.sources) == len(versions)
        assert len({v['sha256'] for v in versions}) == len(versions)
        if demo.get('recording_release'):
            history = root.parent / 'docs/release-1.0/history'
            record_path = history / ('TWOS-' + demo['version'] + '-release.json')
            assert record_path.resolve().is_relative_to(history.resolve())
            assert record_path == root.parent / demo['recording_release']
            record = json.loads(record_path.read_text())
            assert all(record[k] == demo[k] for k in ('version', 'build', 'source_commit'))
            archived = {v['narration']: v['sha256'] for v in record['demo']['versions']}
            assert archived == {v['narration']: v['sha256'] for v in versions}
            assert 'Recorded with TWOS ' + demo['version'] in html
        else:
            assert all(demo[key] == interface[key] for key in ('version', 'build', 'source_commit'))
        poster = (root / demo['poster']).resolve()
        assert poster.is_relative_to(root) and hashlib.sha256(poster.read_bytes()).hexdigest() == demo['poster_sha256']
        for video, source, version in zip(document.videos, document.sources, versions):
            assert 'controls' in video and 'playsinline' in video and 'autoplay' not in video
            assert video['poster'] == './' + demo['poster'] + '?film=' + demo['poster_sha256'][:12]
            assert version['url_suffix'] == '?film=' + version['sha256'][:12]
            assert source == {'src': './' + version['path'] + version['url_suffix'], 'type': 'video/mp4'}
            assert version['captions'] == ['en', 'zh-CN'] and demo['audio']
            file = (root / version['path']).resolve()
            assert file.is_relative_to(root) and file.stat().st_size == version['bytes']
            assert hashlib.sha256(file.read_bytes()).hexdigest() == version['sha256']
            assert any(link['href'] == source['src'] and link.get('download') == version['download_as'] for link in document.links)
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
