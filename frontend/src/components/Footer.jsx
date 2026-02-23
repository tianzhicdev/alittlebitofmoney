import { Link } from 'react-router-dom';

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-links">
        <a href="mailto:hello@alittlebitofmoney.com">Contact Us</a>
        <Link to="/doc#api-policy">Policy</Link>
        <Link to="/doc#terms">Terms</Link>
      </div>
      <div>
        Version <span>v0.2.0</span> | <span>{new Date().getFullYear()}</span> | alittlebitofmoney.com
      </div>
    </footer>
  );
}
