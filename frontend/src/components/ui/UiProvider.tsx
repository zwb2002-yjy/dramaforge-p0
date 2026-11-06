import { ConfigProvider, theme, type ThemeConfig } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useMemo, type ReactNode } from "react";

function workstationTheme(): ThemeConfig {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string) => css.getPropertyValue(name).trim() || undefined;
  const pixels = (name: string) => {
    const value = token(name);
    if (!value) return undefined;
    return parseFloat(value) * (value.endsWith("rem") ? parseFloat(css.fontSize) || 16 : 1);
  };
  return {
    algorithm: theme.darkAlgorithm,
    cssVar: { key: "dramaforge" },
    token: {
      colorPrimary: token("--df-verdigris"),
      colorInfo: token("--df-verdigris"),
      colorSuccess: token("--df-success"),
      colorWarning: token("--df-warning"),
      colorError: token("--df-danger"),
      colorBorder: token("--df-border"),
      colorBorderSecondary: token("--df-border-subtle"),
      colorBgBase: token("--df-surface-0"),
      colorBgContainer: token("--df-surface-1"),
      colorBgElevated: token("--df-surface-2"),
      colorText: token("--df-text-primary"),
      colorTextSecondary: token("--df-text-secondary"),
      fontFamily: token("--df-font-sans"),
      fontSize: pixels("--df-font-size-body"),
      fontSizeHeading1: pixels("--df-page-title-size"),
      fontSizeHeading2: pixels("--df-text-xl"),
      controlHeight: pixels("--df-control-height"),
      controlHeightLG: pixels("--df-control-height-lg"),
      fontSizeLG: pixels("--df-font-size-body-lg"),
      borderRadius: pixels("--df-radius-control"),
      borderRadiusLG: pixels("--df-radius-container"),
      motion: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    },
    components: {
      Button: {
        primaryColor: token("--df-text-inverse"),
        colorTextLightSolid: token("--df-text-inverse"),
      },
      Card: { bodyPadding: pixels("--df-space-5"), bodyPaddingSM: pixels("--df-space-4") },
      Form: { itemMarginBottom: 0 },
      Tabs: { horizontalMargin: "0" },
      Typography: { titleMarginTop: 0, titleMarginBottom: 0 },
      Table: {
        cellFontSize: pixels("--df-font-size-body-lg"),
        cellFontSizeMD: pixels("--df-font-size-body-lg"),
        cellFontSizeSM: pixels("--df-font-size-body"),
      },
    },
  };
}

/** Ant Design owns control recipes; the project supplies its existing design tokens. */
export function UiProvider({ children }: { children: ReactNode }) {
  const config = useMemo(workstationTheme, []);
  return (
    <ConfigProvider locale={zhCN} theme={config} button={{ autoInsertSpace: false }}>
      {children}
    </ConfigProvider>
  );
}
