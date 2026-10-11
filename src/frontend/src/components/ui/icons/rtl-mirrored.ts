/**
 * Иконки, которые в RTL отражаются по горизонтали (SYS-07-R18, стартовый
 * перечень; окончательный — по ревью носителем арабского языка, OQ-82).
 * Не зеркалируются: Play, Pause, Volume2, VolumeX, Check, X, Search, Clock,
 * Calendar, RotateCw, RotateCcw, RefreshCw, Trash2, Settings, User, Globe,
 * Languages.
 */
export const RTL_MIRRORED_ICONS = [
  'ArrowLeft',
  'ArrowRight',
  'ArrowLeftRight',
  'ArrowUpLeft',
  'ArrowUpRight',
  'ArrowDownLeft',
  'ArrowDownRight',
  'ChevronLeft',
  'ChevronRight',
  'ChevronsLeft',
  'ChevronsRight',
  'ChevronFirst',
  'ChevronLast',
  'CornerDownLeft',
  'CornerDownRight',
  'CornerUpLeft',
  'CornerUpRight',
  'Undo2',
  'Redo2',
  'Reply',
  'ReplyAll',
  'Forward',
  'LogIn',
  'LogOut',
  'PanelLeft',
  'PanelRight',
  'PanelLeftOpen',
  'PanelLeftClose',
  'PanelRightOpen',
  'PanelRightClose',
  'Indent',
  'Outdent',
  'ListStart',
  'ListEnd',
  'SkipBack',
  'SkipForward',
  'StepBack',
  'StepForward',
  'MessageSquareReply',
  'Send',
  'ExternalLink',
  'TextQuote',
] as const;

export type RtlMirroredIconName = (typeof RTL_MIRRORED_ICONS)[number];

const MIRRORED = new Set<string>(RTL_MIRRORED_ICONS);

export const isRtlMirroredIcon = (name: string): boolean => MIRRORED.has(name);
