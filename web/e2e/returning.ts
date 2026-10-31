// The storage state of a returning visitor, for contexts a test makes itself with
// `browser.newContext` (the config's `storageState` only reaches the default `page`): without it the
// overview would open over the map on that context's first load.
export const returning = {
  cookies: [],
  origins: [{ origin: 'http://localhost:5174', localStorage: [{ name: 'ehe.overview.seen', value: '1' }] }],
};
