import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Agentes from "./pages/Agentes";
import Alertas from "./pages/Alertas";
import Campo from "./pages/Campo";
import CadastroEquipamento from "./pages/CadastroEquipamento";
import FichaEquipamento from "./pages/FichaEquipamento";
import Inventario from "./pages/Inventario";
import Qualidade from "./pages/Qualidade";
import { EditorTipoPagina, ListaTipos } from "./pages/Tipos";
import { Carregando, Vazio } from "./components/ui";

// A central (mapa, gráficos) fica num pacote separado: o inventário abre sem carregá-la.
const Central = lazy(() => import("./pages/Central"));
// Parte 3: telas de previsão, também em pacotes separados.
const Amanha = lazy(() => import("./pages/Amanha"));
const EquipamentosRisco = lazy(() => import("./pages/EquipamentosRisco"));
const Planejamento = lazy(() => import("./pages/Planejamento"));

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/campo/*" element={<Campo />} />
        <Route path="/central" element={<Suspense fallback={<Carregando texto="Abrindo a central…" />}><Central /></Suspense>} />
        <Route path="/amanha" element={<Suspense fallback={<Carregando texto="Abrindo as previsões…" />}><Amanha /></Suspense>} />
        <Route element={<Layout />}>
          <Route path="previsao/equipamentos" element={<Suspense fallback={<Carregando />}><EquipamentosRisco /></Suspense>} />
          <Route path="previsao/equipes" element={<Suspense fallback={<Carregando />}><Planejamento /></Suspense>} />
          <Route index element={<Inventario />} />
          <Route path="equipamentos/novo" element={<CadastroEquipamento />} />
          <Route path="equipamentos/:id" element={<FichaEquipamento />} />
          <Route path="equipamentos/:id/editar" element={<CadastroEquipamento />} />
          <Route path="agentes" element={<Agentes />} />
          <Route path="alertas" element={<Alertas />} />
          <Route path="qualidade" element={<Qualidade />} />
          <Route path="tipos" element={<ListaTipos />} />
          <Route path="tipos/novo" element={<EditorTipoPagina />} />
          <Route path="tipos/:id" element={<EditorTipoPagina />} />
          <Route path="*" element={<Vazio titulo="Página não encontrada" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
