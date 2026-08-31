import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        graphite: "#202020",
        canvas: "#ffffff",
        ash: "#efefef",
        fog: "#f5f5f5",
        ivory: "#ebe6dd",
        steel: "#4d4d4d",
        slate: "#828282",
        mist: "#e8e8e8",
        ember: "#ff682c",
        brass: "#816729",
      },
      fontFamily: {
        display: ["PolySans", "Inter Tight", "Space Grotesk", "Inter", "system-ui", "sans-serif"],
        body: ["Inter", "system-ui", "sans-serif"],
      },
      fontSize: {
        caption: ["14px", { lineHeight: "1.43" }],
        subheading: ["18px", { lineHeight: "1.25" }],
        heading: ["32px", { lineHeight: "1.19", letterSpacing: "-0.64px" }],
        "heading-lg": ["40px", { lineHeight: "1.2", letterSpacing: "-0.8px" }],
        display: ["66px", { lineHeight: "0.91", letterSpacing: "-1.32px" }],
      },
      letterSpacing: {
        display: "-0.02em",
      },
      borderRadius: {
        DEFAULT: "0px",
        sm: "3px",
        md: "6px",
        lg: "8px",
        xl: "12px",
        "2xl": "20px",
        full: "200px",
      },
      maxWidth: {
        site: "1440px",
      },
      spacing: {
        section: "80px",
        card: "40px",
        element: "20px",
      },
    },
  },
  plugins: [],
};

export default config;
