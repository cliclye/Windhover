import type { ReactNode } from "react";

function Svg({ size = 16, children, sw = 1.7 }: { size?: number; children: ReactNode; sw?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={sw}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

type P = { size?: number };

export const SendIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />
  </Svg>
);
export const StopIcon = ({ size }: P) => (
  <Svg size={size}>
    <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none" />
  </Svg>
);
export const PlusIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);
export const ChatIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M20 12.5a7.5 7.5 0 0 1-11.2 6.5L4 20l1.1-4.3A7.5 7.5 0 1 1 20 12.5Z" />
  </Svg>
);
export const LibraryIcon = ({ size }: P) => (
  <Svg size={size}>
    <rect x="4" y="4" width="6.5" height="6.5" rx="1.6" />
    <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6" />
    <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6" />
    <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6" />
  </Svg>
);
export const AgentIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="m8 9-3 3 3 3M16 9l3 3-3 3M13.5 6l-3 12" />
  </Svg>
);
export const GaugeIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M4.5 16.5a8 8 0 1 1 15 0" />
    <path d="m12 13 4-4.5" />
    <circle cx="12" cy="13.2" r="1.1" fill="currentColor" stroke="none" />
  </Svg>
);
export const GearIcon = ({ size }: P) => (
  <Svg size={size}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
  </Svg>
);
export const SearchIcon = ({ size }: P) => (
  <Svg size={size}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-4.2-4.2" />
  </Svg>
);
export const TrashIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M4.5 7h15M10 11v6M14 11v6M6 7l1 12.5a1.5 1.5 0 0 0 1.5 1.5h7a1.5 1.5 0 0 0 1.5-1.5L18 7M9 7V4.5h6V7" />
  </Svg>
);
export const CopyIcon = ({ size }: P) => (
  <Svg size={size}>
    <rect x="8.5" y="8.5" width="11" height="11" rx="2" />
    <path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5" />
  </Svg>
);
export const CheckIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Svg>
);
export const RetryIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M4.5 12a7.5 7.5 0 0 1 13-5.1L19.5 9M19.5 4.5V9H15M19.5 12a7.5 7.5 0 0 1-13 5.1L4.5 15M4.5 19.5V15H9" />
  </Svg>
);
export const ChevronIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="m7 10 5 5 5-5" />
  </Svg>
);
export const FolderIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5Z" />
  </Svg>
);
export const FileIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M13.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8.5Z" />
    <path d="M13.5 3.5v5h5" />
  </Svg>
);
export const DownloadIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M12 4.5v11M7 11l5 5 5-5M5 19.5h14" />
  </Svg>
);
export const InfoIcon = ({ size }: P) => (
  <Svg size={size}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11v5.5M12 7.8v.2" />
  </Svg>
);
export const BoltIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M13 3.5 5.5 13.5H12L11 20.5l7.5-10H12Z" />
  </Svg>
);
export const MemoryIcon = ({ size }: P) => (
  <Svg size={size}>
    <rect x="4" y="7" width="16" height="10" rx="1.5" />
    <path d="M8 7v10M12 7v10M16 7v10M7 17v2.5M17 17v2.5" />
  </Svg>
);
export const SunIcon = ({ size }: P) => (
  <Svg size={size}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" />
  </Svg>
);
export const MoonIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10Z" />
  </Svg>
);
export const SidebarIcon = ({ size }: P) => (
  <Svg size={size}>
    <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
    <path d="M9.5 4.5v15" />
  </Svg>
);
export const SparkIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M12 3.5 13.8 10l6.7 2-6.7 2L12 20.5 10.2 14l-6.7-2 6.7-2Z" />
  </Svg>
);
export const ExternalIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="M13.5 4.5h6v6M19.5 4.5 11 13M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" />
  </Svg>
);
export const CloseIcon = ({ size }: P) => (
  <Svg size={size}>
    <path d="m6 6 12 12M18 6 6 18" />
  </Svg>
);
