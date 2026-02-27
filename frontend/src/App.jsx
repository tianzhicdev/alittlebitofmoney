import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import Footer from './components/Footer';
import Navbar from './components/Navbar';
import Catalog from './pages/Catalog';
import Doc from './pages/Doc';
import Home from './pages/Home';
import AIForHire from './pages/AIForHire';

function Layout() {
  const location = useLocation();

  return (
    <div className="site-shell">
      <Navbar />
      <main key={location.pathname} className="page-content">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/doc" element={<Doc />} />
        <Route path="/ai-for-hire" element={<AIForHire />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
