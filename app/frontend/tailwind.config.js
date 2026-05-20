/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // "cool generic e-commerce" palette: deep ink + neon accent
        ink: {
          50:  '#f5f7fb',
          100: '#e9eef7',
          200: '#cdd6e6',
          300: '#9aa8c4',
          400: '#6c7c9d',
          500: '#475573',
          600: '#2f3a55',
          700: '#1e273d',
          800: '#121828',
          900: '#0a0e1a',
        },
        accent: {
          DEFAULT: '#7c5cff', // electric indigo
          glow: '#a594ff',
        },
        lime: {
          DEFAULT: '#c8ff5e', // for "similarity" pills
        },
      },
      fontFamily: {
        display: ['"DM Sans"', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        glow: '0 0 32px -4px rgba(124, 92, 255, 0.45)',
      },
    },
  },
  plugins: [],
};
