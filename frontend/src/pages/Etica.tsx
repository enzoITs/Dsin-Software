import { Link } from "react-router-dom";

const PREVISTO = [
  ["Falha de equipamento (P1)", "equipamento, 7 e 30 dias"],
  ["Ocorrências e índice de risco (P2, P3)", "região × hora"],
  ["Reforço de equipes (P4)", "região × período"],
  ["Anomalias (P5)", "equipamento ou região"],
  ["Disponibilidade e carga de manutenção (P6, P8)", "região, tipo, semana"],
  ["Risco de furto (P7)", "equipamento, 30 dias"],
  ["Expansão de câmeras (C2)", "célula de 400 m"],
];

const NUNCA = ["Quem vai cometer uma infração ou um crime", "Onde uma pessoa vai estar", "Perfil, rosto, placa ou trajeto de alguém",
  "Suspeitos", "Desempenho individual de servidores ou agentes"];

const LIMITES = [
  ["P1 falha", "Ordena bem, mas a maioria das falhas ainda é acaso. Não substitui a preventiva."],
  ["P2 ocorrências", "Ganho moderado sobre a média histórica; eventos não cadastrados não são previstos."],
  ["P3 índice", "Pesos fixos e configuráveis, não aprendidos: é uma síntese para decidir."],
  ["P4 equipes", "Só tão boa quanto a P2; não considera o trânsito entre regiões."],
  ["P5 anomalias", "Uma anomalia que dura mais da metade da janela vira o novo normal."],
  ["P6 disponibilidade", "Em 30 dias ganha pouco da média móvel (dito no cartão); em 90 dias, mais."],
  ["P7 furto", "Evento raro: probabilidades pequenas e incertas. Não sabe a hora do furto."],
  ["P8 carga", "Horas por serviço e peças vêm de configuração, não de dados."],
  ["C2 expansão", "Não sabe se há poste, energia ou visada: avaliar no local."],
  ["Fim de vida", "Vida útil por tipo vem de configuração; \"se fosse novo\" é um contrafactual do modelo."],
];

function Bloco({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-linha pt-4">
      <h2 className="mb-2 text-[15px] font-bold">{titulo}</h2>
      <div className="space-y-2 text-[14px] leading-relaxed">{children}</div>
    </section>
  );
}

export default function Etica() {
  return (
    <div className="mx-auto max-w-[900px] space-y-5">
      <div>
        <h1 className="text-[26px] font-bold tracking-[-0.02em]">Ética e limites</h1>
        <p className="mt-1 border-l-[4px] border-acento bg-neutro px-3 py-2 text-[15px] font-semibold">
          O Atalaia prevê lugares, períodos e equipamentos. Nunca pessoas. Quem decide é sempre uma pessoa.
        </p>
      </div>

      <Bloco titulo="O que é previsto e o que não é">
        <div className="grid gap-4 md:grid-cols-2">
          <ul className="space-y-1">
            {PREVISTO.map(([o, u]) => <li key={o}><b>{o}</b> <span className="text-cinza">· {u}</span></li>)}
          </ul>
          <div>
            <p className="font-semibold">Nunca previsto</p>
            <ul className="list-disc pl-5">{NUNCA.map((n) => <li key={n}>{n}</li>)}</ul>
          </div>
        </div>
        <p className="text-[13px] text-cinza">
          Nenhum dado usado pelos modelos tem nome, documento, placa, imagem ou posição de pessoas. A escala de agentes entra como número de
          agentes por região e hora. Fora do escopo: reconhecimento facial, rastreamento de placas, bases policiais reais e decisão automática.
        </p>
      </Bloco>

      <Bloco titulo="Viés de registro">
        <p>
          Ocorrência registrada não é ocorrência acontecida: onde há mais agentes, mais coisas são vistas. Um modelo ingênuo mandaria mais
          agentes para onde já há agentes, e o ciclo se alimentaria sozinho.
        </p>
        <ul className="list-disc pl-5">
          <li>Cada ocorrência guarda quantos agentes estavam em turno na região; o modelo usa isso para separar "aconteceu mais" de "foi mais visto".</li>
          <li>Nos cenários "e se", mudar o número de equipes não muda as ocorrências previstas: tirar equipes não reduz ocorrências, só deixa de vê-las.</li>
          <li>O reforço de equipes tem mínimo por região e teto de deslocamentos: nenhuma região fica descoberta para alimentar outra.</li>
        </ul>
      </Bloco>

      <Bloco titulo="Furto de equipamento sem vigiar pessoas">
        <p>
          O risco de furto usa só características do ponto: furtos de equipamento já registrados por perto, vandalismo de madrugada no
          bairro, distância até a câmera mais próxima, agentes de madrugada na região, tipo e idade do equipamento. As ações são sobre o
          ponto: ronda, fixação, câmera. Mais furtos por perto ou câmera mais longe nunca diminuem o risco (restrição do modelo).
        </p>
      </Bloco>

      <Bloco titulo="O humano decide">
        <ul className="list-disc pl-5">
          <li>Toda recomendação tem Aceitar, Ajustar e Rejeitar. Rejeitar exige motivo. Tudo fica registrado em <Link className="underline" to="/previsao/decisoes">Decisões</Link>.</li>
          <li>O perfil automático não pode decidir (a API recusa).</li>
          <li>Aceitar executa só o que está escrito no cartão.</li>
          <li>Os modelos não se retreinam sozinhos: o monitor avisa e o gestor decide.</li>
          <li>O copiloto só lê e simula.</li>
        </ul>
      </Bloco>

      <Bloco titulo="Transparência e incerteza">
        <ul className="list-disc pl-5">
          <li>Todo cartão responde: o que estamos prevendo, com base em quê e como isso ajuda, com os fatores que mais pesaram.</li>
          <li>Toda previsão tem faixa provável e diz a confiança; a confiança baixa é dita abertamente.</li>
          <li>Todo modelo aparece ao lado da média histórica, no passado (backtest) e na operação (<Link className="underline" to="/previsao/confianca">Confiança</Link>).</li>
        </ul>
      </Bloco>

      <Bloco titulo="Dados sintéticos">
        <p>
          Todos os dados desta demonstração são sintéticos, gerados com padrões conhecidos. Os modelos não leem a descrição dos padrões, e a
          tela de confiança mostra quais foram redescobertos. Isso prova que o método funciona, não que os números valem para uma cidade
          real. Antes de usar de verdade: treinar com dados reais por pelo menos um ano, medir o viés de registro com fontes independentes,
          medir o desempenho por região e ter uma política pública de uso revisada periodicamente.
        </p>
      </Bloco>

      <Bloco titulo="Limites de cada módulo">
        <table className="w-full border-collapse text-[13px]">
          <tbody>
            {LIMITES.map(([m, l]) => (
              <tr key={m} className="border-b border-linha align-top"><td className="w-[170px] py-1 pr-3 font-semibold">{m}</td><td className="py-1">{l}</td></tr>
            ))}
          </tbody>
        </table>
      </Bloco>
    </div>
  );
}
