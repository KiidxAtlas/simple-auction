"""Execute the served JavaScript with a minimal DOM; no network or browser needed.

These state-machine checks do not replace rendered mobile-browser verification.
Node is optional for the Python-only development environment.
"""

import re
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

from simple_auction.services.phone_capture import _phone_page

SCRIPT_CHECKS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const script = require('node:fs').readFileSync(0, 'utf8');
const elements = Object.fromEntries([
  'photo', 'camera', 'take', 'choose', 'send', 'status', 'preview',
  'preview-box', 'filename', 'remove', 'shot'
].map(id => [id, {
  value: '', files: [], disabled: false, hidden: false, dataset: {},
  removeAttribute(key) { delete this[key]; },
  click() { this.clicked = (this.clicked || 0) + 1; },
  focus() { this.focused = true; }
}]));
const revoked = [], requests = [];
let respond;
const context = {
  document: {getElementById: id => elements[id]},
  location: {pathname: '/session-token/'},
  URL: {
    createObjectURL: () => 'blob:preview',
    revokeObjectURL: url => revoked.push(url)
  },
  fetch: (url, options) => {
    requests.push({url, options});
    return new Promise((resolve, reject) => { respond = {resolve, reject}; });
  }
};
vm.runInNewContext(script, context);
const {photo, camera, take, choose: chooseButton, send, status, preview, filename, remove, shot} = elements;
const previewBox = elements['preview-box'];
const file = {name: '<photo>.jpg', type: 'image/jpeg', size: 2048};
function choose(selected) {
  photo.files = selected ? [selected] : [];
  photo.value = selected ? 'selected' : '';
  photo.onchange();
}
(async () => {
  take.onclick();
  assert.equal(camera.clicked, 1);
  assert.equal(photo.clicked, undefined);
  chooseButton.onclick();
  assert.equal(photo.clicked, 1);
  choose(file);
  assert.equal(send.disabled, false);
  assert.equal(previewBox.hidden, false);
  assert.equal(filename.textContent, '<photo>.jpg');
  assert.equal(requests.length, 0); // selection must never send automatically
  remove.onclick();
  assert.equal(photo.value, '');
  assert.equal(previewBox.hidden, true);
  assert.equal(send.disabled, true);
  assert.equal(chooseButton.focused, true);
  assert.equal(revoked.length, 1);
  for (const invalid of [
    {...file, type: 'image/heic'}, {...file, size: 12582913}, {...file, size: 0}
  ]) {
    choose(invalid);
    assert.equal(send.disabled, true);
    assert.equal(previewBox.hidden, true);
    assert.equal(status.dataset.state, 'error');
  }
  choose(null);
  assert.equal(send.disabled, true);
  camera.files = [file];
  camera.value = 'captured';
  camera.onchange();
  assert.equal(previewBox.hidden, false);
  chooseButton.onclick();
  choose(null); // cancelling the other picker must keep the camera selection
  assert.equal(send.disabled, false);
  shot.value = 'serial';
  const first = send.onclick();
  assert.equal(send.disabled, true);
  assert.equal(photo.disabled, true);
  assert.equal(shot.disabled, true);
  assert.equal(remove.disabled, true);
  assert.equal(take.disabled, true);
  assert.equal(chooseButton.disabled, true);
  assert.equal(camera.disabled, true);
  take.onclick();
  chooseButton.onclick();
  assert.equal(camera.clicked, 1);
  assert.equal(photo.clicked, 2);
  await send.onclick();
  assert.equal(requests.length, 1); // repeated taps must not double-upload
  assert.equal(requests[0].url, '/session-token/upload/?shot=serial');
  assert.equal(requests[0].options.body, file);
  assert.equal(requests[0].options.headers['Content-Type'], 'image/jpeg');
  respond.resolve({ok: false, text: async () => 'Session limit reached'});
  await first;
  assert.equal(status.dataset.state, 'error');
  assert.equal(status.textContent, 'Session limit reached');
  assert.equal(previewBox.hidden, false); // retain the photo for review/retry
  assert.equal(send.disabled, false);
  assert.equal(photo.disabled, false);
  const second = send.onclick();
  respond.reject(new Error('Disconnected'));
  await second;
  assert.equal(status.dataset.state, 'error');
  assert.equal(send.disabled, false);
  assert.equal(shot.disabled, false);
  assert.equal(previewBox.hidden, false);
  const third = send.onclick();
  respond.resolve({ok: true, text: async () => 'Photo received.'});
  await third;
  assert.equal(status.dataset.state, 'success');
  assert.equal(photo.value, '');
  assert.equal(preview.src, undefined);
  assert.equal(previewBox.hidden, true);
  assert.equal(send.disabled, true);
  assert.equal(photo.disabled, false);
  assert.equal(remove.disabled, false);
  assert.equal(take.disabled, false);
  assert.equal(chooseButton.disabled, false);
  assert.equal(camera.disabled, false);
  assert.equal(camera.value, '');
  choose(file); // choosing the same file again can start another shot
  assert.equal(send.disabled, false);
  assert.equal(previewBox.hidden, false);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def test_phone_script_selection_sending_errors_and_retry():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to execute phone-page JavaScript checks")
    page = _phone_page(41000, "test-nonce")
    script = re.search(r'<script nonce="test-nonce">(.*?)</script>', page, re.DOTALL)
    assert script is not None
    result = subprocess.run(
        [node, "-e", SCRIPT_CHECKS],
        input=script.group(1),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_file_picker_does_not_force_camera_capture():
    class Controls(HTMLParser):
        def __init__(self):
            super().__init__()
            self.controls = {}

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag in {"input", "button"}:
                self.controls[attributes["id"]] = attributes

    parser = Controls()
    parser.feed(_phone_page(41000, "test-nonce"))
    controls = parser.controls
    assert controls["photo"]["type"] == "file"
    assert "capture" not in controls["photo"]
    assert controls["camera"]["type"] == "file"
    assert controls["camera"]["capture"] == "environment"
    assert controls["photo"]["accept"] == controls["camera"]["accept"]
    for button in ("take", "choose"):
        assert controls[button]["type"] == "button"
        assert "hidden" not in controls[button]
        assert "disabled" not in controls[button]
