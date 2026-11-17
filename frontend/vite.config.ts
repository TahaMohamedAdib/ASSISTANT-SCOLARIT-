import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const branding = {
  identity: {
    name: 'Assistant Scolarité EIH',
    institution: 'École d’Ingénieurs Hélianthe',
  },
  theme: {
    'font-body': "'DM Sans', ui-sans-serif, system-ui, sans-serif",
    'font-display': 'Manrope, ui-sans-serif, system-ui, sans-serif',
    'color-canvas': '#100f16',
    'color-text': '#f6f1e9',
    'color-muted': '#b7b1be',
    'color-accent': '#ff9d70',
    'color-action': '#ef9266',
    'color-on-action': '#271410',
    'color-panel': '#24202b',
    'color-field': 'rgb(8 8 12 / 44%)',
    'color-border': 'rgb(255 255 255 / 16%)',
    'color-info': '#b7e6ef',
    'color-info-bg': 'rgb(58 128 149 / 17%)',
    'color-success': '#b2edcf',
    'color-success-bg': 'rgb(111 205 171 / 10%)',
    'color-danger': '#ffd0bf',
    'color-danger-bg': 'rgb(125 40 29 / 36%)',
    'radius-control': '10px',
    'radius-notice': '12px',
  },
}

export default defineConfig({
  define: {
    __APP_BRAND__: JSON.stringify(branding.identity),
  },
  plugins: [
    react(),
    {
      name: 'eih-branding',
      transformIndexHtml: () => [
        { tag: 'title', children: branding.identity.name, injectTo: 'head' },
        { tag: 'meta', attrs: { name: 'theme-color', content: branding.theme['color-canvas'] }, injectTo: 'head' },
        {
          tag: 'style',
          children: `:root { ${Object.entries(branding.theme).map(([name, value]) => `--${name}: ${value};`).join(' ')} }`,
          injectTo: 'head-prepend',
        },
      ],
    },
  ],
})
