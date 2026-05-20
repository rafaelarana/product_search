import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import App from './App';
import SearchPage from './pages/Search';
import ProductPage from './pages/Product';
import './styles/index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          {/* Standard mode */}
          <Route path="/" element={<SearchPage mode="standard" />} />
          <Route path="/product/:id" element={<ProductPage mode="standard" />} />
          {/* Turbo mode (LRU embed cache + precomputed similars) */}
          <Route path="/turbo" element={<SearchPage mode="turbo" />} />
          <Route path="/turbo/product/:id" element={<ProductPage mode="turbo" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
