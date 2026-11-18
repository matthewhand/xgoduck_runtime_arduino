const STOCK_WALK = '1fc079512fe3fe23e274e7a9d8c9ad007e88439f0385ecf20c9596e57886249f';
const STOCK_GETUP = '0aa9466310dddc17438e42a28d9fa20bd869b4ee0568c7b6d5bfef85e53cbb94';

// Add an entry only after the training record identifies this complete mass
// layout. Values identify the exact ONNX sessions required on the board.
export const TRAINED_LAYOUTS = {
  'v5-stock-feet': {walk: STOCK_WALK, getup: STOCK_GETUP},
};

export function modPolicyStatus(backpack, skates, packet, profiles = TRAINED_LAYOUTS, {teeth = false, tusks = false, tail = false} = {}) {
  const base = 'v5-' + (tail ? 'articulated-tail-r1' : backpack ? 'top-entry-wired-contact-r1' : 'stock') + (skates ? '-skates' : '-feet');
  const layout = base + (teeth ? '-teeth-r2' : '') + (tusks ? '-tusks-r2' : '');
  const expected = profiles[layout];
  const roles = [skates ? 'roller' : 'walk', 'getup'];
  const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
  if (!expected || !roles.every(role => digest(expected[role]))) {
    if (teeth && !tail && !backpack && !skates && !tusks && modPolicyStatus(false, false, packet, profiles).state === 'matched') {
      return {state: 'candidate', text: 'Stock models loaded. Teeth are a transfer candidate. Confirm fit and test the printed head.'};
    }
    return {state: 'untrained', text: 'No qualified ' + (skates ? 'skating' : 'walking') +
      ' and get-up policy pair is registered for this weight layout.'};
  }
  if (!packet) return {state: 'offline', text: 'Board status unavailable. Loaded policies cannot be verified.'};
  const loaded = packet.loaded_policy_sha256;
  if (!loaded || roles.some(role => !Object.hasOwn(loaded, role) || loaded[role] === 'unverified')) {
    return {state: 'unverified', text: 'The board has not reported the loaded policy fingerprints for this layout.'};
  }
  const missing = roles.filter(role => loaded[role] !== expected[role]);
  if (missing.length) return {state: 'mismatch', text: 'Required model not loaded for this layout: ' + missing.join(', ') + '.'};
  if (expected.transferReport) return {state: 'transfer', text: 'Board sessions match the models qualified by a transfer test for this layout.'};
  return {state: 'matched', text: 'Board sessions match the trained motion and get-up models for this layout.'};
}
