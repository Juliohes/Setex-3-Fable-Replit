/** Theming multi-tenant: los colores reales llegan como CSS variables desde
 * /api/v1/branding (S4.2). Aquí solo se mapean a utilidades. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: "rgb(var(--color-primary) / <alpha-value>)",
        surface: "rgb(var(--color-secondary) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
