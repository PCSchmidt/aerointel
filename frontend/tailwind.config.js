/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      borderRadius: {
        DEFAULT: '0',
        none: '0',
        sm: '0',
        md: '0',
        lg: '0',
        xl: '0',
        '2xl': '0',
        '3xl': '0',
        full: '9999px',
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'Manrope', 'Segoe UI', 'sans-serif'],
        serif: ['var(--font-display)', 'Cormorant Garamond', 'Georgia', 'serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
