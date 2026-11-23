import {mountMatrixControls} from './matrix-ui.mjs?v=2';

const boardUrl = new URL(location.href);
const isLocal = ['localhost', '127.0.0.1', '[::1]'].includes(boardUrl.hostname);
if (!isLocal) {
  const rebootUrl = new URL('/', boardUrl);
  rebootUrl.protocol = 'http:';
  rebootUrl.port = '9528';
  const reboot = document.getElementById('wifi-reboot');
  reboot.href = rebootUrl.href;
  reboot.hidden = false;
} else {
  document.getElementById('wifi-reboot-note').hidden = false;
}
mountMatrixControls();
