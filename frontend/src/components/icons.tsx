import type { ReactNode } from "react";

// One small icon set, drawn at 16px with a 1.75 stroke so every control reads as one family.
function Icon({ children, size = 16 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      {children}
    </svg>
  );
}

export const ExpandIcon = () => (
  <Icon>
    <path d="M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9" />
  </Icon>
);

export const CloseIcon = () => (
  <Icon>
    <path d="m3.5 3.5 9 9M12.5 3.5l-9 9" />
  </Icon>
);

export const PlusIcon = () => (
  <Icon>
    <path d="M8 3v10M3 8h10" />
  </Icon>
);

export const MinusIcon = () => (
  <Icon>
    <path d="M3 8h10" />
  </Icon>
);

export const ResetIcon = () => (
  <Icon>
    <path d="M2.75 8a5.25 5.25 0 1 0 1.6-3.75M2.75 2.5v2.75H5.5" />
  </Icon>
);

export const InfoIcon = () => (
  <Icon>
    <circle cx="8" cy="8" r="6" />
    <path d="M8 7.25v3.5M8 5.25v.01" />
  </Icon>
);
