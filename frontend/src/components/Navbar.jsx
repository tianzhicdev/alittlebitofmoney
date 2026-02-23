import { Link, NavLink } from 'react-router-dom';

function navClass({ isActive }) {
  return `nav-link ${isActive ? 'active' : ''}`.trim();
}

export default function Navbar() {
  return (
    <header className="top-nav">
      <Link className="brand" to="/">
        <span className="brand-core">A LITTLE BIT OF </span>
        <span className="brand-accent">MONEY</span>
      </Link>
      <nav className="nav-links" aria-label="Main Navigation">
        <NavLink to="/" className={navClass} end>
          Home
        </NavLink>
        <NavLink to="/catalog" className={navClass}>
          API Catalog
        </NavLink>
        <NavLink to="/doc" className={navClass}>
          Developer Guide
        </NavLink>
      </nav>
    </header>
  );
}
