// Hypit 0.1.8's capture child starts tsx without its distribution resolver.
// Preload the same resolvers as bin/hypit.mjs in each inherited Node process.
// Keep this workaround outside the installed package so it is reproducible.
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';

const distribution = new URL('../vendor/hypit-runtime/node_modules/@hypit/hypit/', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('package.json', distribution), 'utf8'));
if (manifest.version !== '0.1.8') {
  throw new Error('Recheck the Hypit renderer bootstrap before changing the pinned 0.1.8 release.');
}
const requireFromDistribution = createRequire(new URL('package.json', distribution));
const { register } = await import(pathToFileURL(requireFromDistribution.resolve('tsx/esm/api')).href);
register();
const {
  installDistributionPackageResolution,
  installExternalPackageResolution,
} = await import(new URL('packages/package-loader-node/src/distribution-resolution.ts', distribution).href);
installDistributionPackageResolution([fileURLToPath(distribution)]);
const { hypitHostPackageRoot } = await import(new URL('packages/runtime-host-node/src/index.ts', distribution).href);
installExternalPackageResolution([hypitHostPackageRoot()]);
