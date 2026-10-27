import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ModoApresentacao from "./components/ModoApresentacao";
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
const Confianca = lazy(() => import("./pages/Confianca"));
const Cenarios = lazy(() => import("./pages/Cenarios"));
const Decisoes = lazy(() => import("./pages/Decisoes"));
const Copiloto = lazy(() => import("./pages/Copiloto"));
const BriefingDia = lazy(() => import("./pages/BriefingDia"));
const Tendencias = lazy(() => import("./pages/Tendencias"));
const RiscoFurto = lazy(() => import("./pages/RiscoFurto"));
const Expansao = lazy(() => import("./pages/Expansao"));
const FimDeVida = lazy(() => import("./pages/FimDeVida"));
const Etica = lazy(() => import("./pages/Etica"));

export default function App() {
  return (
    <BrowserRouter>
      <ModoApresentacao />
      <Routes>
        <Route path="/campo/*" element={<Campo />} />
        <Route path="/central" element={<Suspense fallback={<Carregando texto="Abrindo a central…" />}><Central /></Suspense>} />
        <Route path="/amanha" element={<Suspense fallback={<Carregando texto="Abrindo as previsões…" />}><Amanha /></Suspense>} />
        <Route element={<Layout />}>
          <Route path="previsao/equipamentos" element={<Suspense fallback={<Carregando />}><EquipamentosRisco /></Suspense>} />
          <Route path="previsao/equipes" element={<Suspense fallback={<Carregando />}><Planejamento /></Suspense>} />
          <Route path="previsao/confianca" element={<Suspense fallback={<Carregando />}><Confianca /></Suspense>} />
          <Route path="previsao/cenarios" element={<Suspense fallback={<Carregando />}><Cenarios /></Suspense>} />
          <Route path="previsao/decisoes" element={<Suspense fallback={<Carregando />}><Decisoes /></Suspense>} />
          <Route path="previsao/copiloto" element={<Suspense fallback={<Carregando />}><Copiloto /></Suspense>} />
          <Route path="previsao/briefing" element={<Suspense fallback={<Carregando />}><BriefingDia /></Suspense>} />
          <Route path="previsao/tendencias" element={<Suspense fallback={<Carregando />}><Tendencias /></Suspense>} />
          <Route path="previsao/furtos" element={<Suspense fallback={<Carregando />}><RiscoFurto /></Suspense>} />
          <Route path="previsao/expansao" element={<Suspense fallback={<Carregando />}><Expansao /></Suspense>} />
          <Route path="previsao/fim-de-vida" element={<Suspense fallback={<Carregando />}><FimDeVida /></Suspense>} />
          <Route path="previsao/etica" element={<Suspense fallback={<Carregando />}><Etica /></Suspense>} />
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
