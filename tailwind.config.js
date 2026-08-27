/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './web/**/*.html',
    './web/**/*.js',
  ],
  // safelist: JS 動態拼接的 class（如 skill/memory toggle 的 peer-checked 變體）
  // 若只用字串拼接、Tailwind JIT 掃描不到，會漏編譯。這裡強制保留。
  safelist: [
    'peer-checked:bg-primary',
    'peer-checked:bg-primary/60',
    'peer-checked:translate-x-4',
    'peer-checked:bg-white',
  ],
  theme: {
    extend: {
      colors: {
        background: 'rgb(var(--color-background) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        surfaceHighlight: 'rgb(var(--color-surface-highlight) / <alpha-value>)',
        primary: 'rgb(var(--color-primary) / <alpha-value>)',
        secondary: 'rgb(var(--color-secondary) / <alpha-value>)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        success: 'rgb(var(--color-success) / <alpha-value>)',
        danger: 'rgb(var(--color-danger) / <alpha-value>)',
        textMain: 'rgb(var(--color-text-primary) / <alpha-value>)',
        textMuted: 'rgb(var(--color-text-muted) / <alpha-value>)',
        textSecondary: 'rgb(var(--color-text-secondary) / <alpha-value>)',
        border: 'rgb(var(--color-border) / <alpha-value>)',
        borderSubtle: 'rgb(var(--color-border-subtle) / <alpha-value>)',
        borderLight: 'rgb(var(--color-border-light) / <alpha-value>)',
      },
      // CJK fallback：Inter / Inter Tight 是純拉丁字體（無中文字形），
      // 中文需顯式 fallback 到高品質繁中 sans，否則會跑出系統明體（serif）。
      // 拉丁字仍優先 Inter / Inter Tight；只有 CJK 字元才落到 Noto Sans TC。
      fontFamily: {
        serif: ['"Inter Tight"', '"Noto Sans TC"', '"PingFang TC"', '"Microsoft JhengHei"', 'system-ui', 'sans-serif'],
        sans: ['Inter', '"Noto Sans TC"', '"PingFang TC"', '"Microsoft JhengHei"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      letterSpacing: {
        tightest: '-0.04em',
        tighter: '-0.03em',
        tightdisplay: '-0.02em',
      },
      borderRadius: {
        '4xl': '2rem',
      },
      animation: {
        'spin-slow': 'spin 20s linear infinite',
      },
    },
  },
  plugins: [],
};
