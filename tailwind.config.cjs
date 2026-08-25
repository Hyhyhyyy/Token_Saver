module.exports = {
  content: ['./frontend/index.html', './frontend/app.js'],
  theme: {
    extend: {
      fontFamily: {
        rounded: ['Quicksand', 'Nunito', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'clay-sm': '4px 4px 8px rgba(0,0,0,0.08), inset 2px 2px 4px rgba(255,255,255,0.5), inset -1px -1px 2px rgba(0,0,0,0.05)',
        'clay-md': '8px 8px 16px rgba(0,0,0,0.1), inset 4px 4px 8px rgba(255,255,255,0.4), inset -2px -2px 4px rgba(0,0,0,0.1)',
        'clay-lg': '12px 12px 24px rgba(0,0,0,0.1), inset 6px 6px 12px rgba(255,255,255,0.6), inset -4px -4px 8px rgba(0,0,0,0.05)',
        'clay-input': 'inset 4px 4px 8px rgba(0,0,0,0.1), inset -4px -4px 8px rgba(255,255,255,0.9)',
        'clay-focus': '8px 8px 16px rgba(0,0,0,0.1), inset 4px 4px 8px rgba(255,255,255,0.4), inset -2px -2px 4px rgba(0,0,0,0.1), 0 0 0 4px rgba(248,180,217,0.3)',
      },
    },
  },
  plugins: [],
}
