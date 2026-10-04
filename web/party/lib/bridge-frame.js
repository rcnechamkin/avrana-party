// bridge.html's only script: start the bridge in this frame. It is useless as a page of its
// own (no parent to talk to), and says nothing to a parent it does not recognise.
import { startBridge } from './bridge.js';

if (globalThis.parent && globalThis.parent !== globalThis) startBridge();
