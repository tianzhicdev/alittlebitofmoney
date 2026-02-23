/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        body: ['"Space Grotesk"', '"Segoe UI"', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SFMono-Regular"', 'monospace'],
      },
    },
  },
  plugins: [],
};
