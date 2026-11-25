import {
  BarChart3, CircleHelp, ClipboardList, Database, FileQuestion, FileUp, NotebookText,
  Settings2, ShieldCheck, TrendingUp
} from "lucide-react";
import cmuLogoFull from "../assets/cmu-logo-full.png";
import cmuLogoFullBlueText from "../assets/cmu-logo-full-blue-text (1).png";
import cmuShield from "../assets/cmu-shield (2).png";

const items = [
  ["Upload", FileUp],
  ["Generate Practice Questions", FileQuestion],
  ["My Progress", TrendingUp],
  ["Saved Questions", NotebookText],
  ["Training Data", Database],
  ["Settings", Settings2],
  ["Help", CircleHelp]
];
const teacherItems = [
  ["Test Builder", ClipboardList],
  ["Item Analysis", BarChart3]
];

export default function Sidebar({ active, onNavigate, open, onClose }) {
  return (
    <>
      {open && <button className="drawer-scrim" aria-label="Close menu" onClick={onClose} />}
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="sidebar-campus-logo">
          <img className="sidebar-campus-logo-dark" src={cmuLogoFullBlueText} alt="City of Malabon University, Founded 2003" />
          <img className="sidebar-campus-logo-pink" src={cmuLogoFull} alt="City of Malabon University, Founded 2003" />
        </div>
        <div className="brand">
          <div className="brand-mark"><img src={cmuShield} alt="" /></div>
          <div className="brand-name">Clinthinker©</div>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="side-nav">
          {items.map(([label, Icon]) => (
            <button key={label} className={`nav-item ${active === label ? "nav-active" : ""}`} onClick={() => onNavigate(label)}>
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
              {active === label && <span className="nav-pip" />}
            </button>
          ))}
          <div className="workspace-label teacher-tools-label">TEACHER TOOLS</div>
          {teacherItems.map(([label, Icon]) => (
            <button key={label} className={`nav-item ${active === label ? "nav-active" : ""}`} onClick={() => onNavigate(label)}>
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
              {active === label && <span className="nav-pip" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-note"><ShieldCheck size={15} /><span>Saved on this device</span></div>
          <div className="offline-sidebar"><span /> OFFLINE READY</div>
        </div>
      </aside>
    </>
  );
}
