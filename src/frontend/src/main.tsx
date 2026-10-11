import * as React from 'react';
import { createRoot } from 'react-dom/client';

import './index.css';
import { App } from './app';
import { registerExtensions } from './app/extensions';
import { registerI18nResources } from './app/i18n-resources';
import { initI18n } from './lib/i18n/i18n';
import { enableMocking } from './testing/mocks';

const root = document.getElementById('root');
if (!root) throw new Error('No root element found');

registerI18nResources();
registerExtensions();

Promise.all([enableMocking(), initI18n()]).then(() => {
  createRoot(root).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
