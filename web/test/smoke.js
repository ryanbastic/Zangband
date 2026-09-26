/*
 * Headless smoke test: runs the WebAssembly build under Node with a
 * stub DOM, types a scripted sequence of keys and prints the screen.
 *
 *   node web/test/smoke.js [keys...]
 *
 * Each argument is typed once the screen has settled; "\e" is Escape,
 * "\r" is Enter, "^X" is a control key.
 */
'use strict';

var path = require('path');

function stubCtx() {
	return new Proxy({ measureText: function () { return { width: 8 }; } }, {
		get: function (t, k) { return k in t ? t[k] : function () {}; },
		set: function (t, k, v) { t[k] = v; return true; }
	});
}
function stubCanvas() {
	return { getContext: stubCtx, parentElement: { clientWidth: 800, clientHeight: 600 },
		style: {}, classList: { add: function () {}, remove: function () {} } };
}
var canvas = stubCanvas();
global.window = { addEventListener: function () {}, devicePixelRatio: 1,
	location: { pathname: '/' }, encodeURIComponent: encodeURIComponent };
global.document = {
	getElementById: function (id) { return id === 'term' ? canvas : null; },
	createElement: stubCanvas,
	addEventListener: function () {}
};

var dist = path.join(__dirname, '..', 'dist');
process.chdir(dist);
global.XMLHttpRequest = undefined;
/* Emscripten would fetch() the .wasm by path; make it read the file */
global.fetch = undefined;
var Module = require(path.join(dist, 'zangband.js'));

function decode(s) {
	return s.replace(/\\e/g, '\x1b').replace(/\\r/g, '\r')
		.replace(/\^([A-Z])/g, function (m, c) { return String.fromCharCode(c.charCodeAt(0) & 31); });
}

var steps = process.argv.slice(2).map(decode);
var last = '', stable = 0;

var timer = setInterval(function () {
	if (!Module.Zangband) return;
	var scr = Module.Zangband.screenText();
	if (scr === last) stable++; else { stable = 0; last = scr; }
	if (stable < 15) return;

	console.log('==========');
	console.log(scr);
	if (!steps.length) {
		clearInterval(timer);
		console.log('Saves: ' + JSON.stringify(Module.FS.readdir('/persist/save')));
		process.exit(0);
	}
	Module.Zangband.type(steps.shift());
	stable = 0;
}, 100);

setTimeout(function () { console.log('TIMEOUT\n' + Module.Zangband.screenText()); process.exit(1); }, 120000);
