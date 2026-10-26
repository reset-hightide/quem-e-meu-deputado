# Monitor de deputados federais

Painel com presença, projetos apresentados e quantos foram aprovados, por deputado federal e por espectro político (esquerda em vermelho, centro em cinza, direita em azul). Os dados vêm dos [Dados Abertos da Câmara](https://dadosabertos.camara.leg.br) e são recalculados todos os dias, sem intervenção manual.

## Como funciona

| Peça | O que faz |
|---|---|
| `atualizar.py` | Baixa os arquivos oficiais (proposições, autores, eventos, presença, votações), calcula os indicadores e grava `deputados.json`. Só usa a biblioteca padrão do Python. |
| `espectro.json` | Tabela partido → esquerda, centro ou direita. É uma convenção simplificada: edite para ajustar. |
| `index.html` | O painel. Lê `deputados.json` e mostra rankings, dispersão, tabela e a ficha de cada deputado. |
| `.github/workflows/atualizar.yml` | GitHub Actions: roda `atualizar.py` todo dia às 06:30 (Brasília) e commita o resultado. |

## Indicadores

- **Projetos apresentados:** PL, PLP, PEC e PDL em que o deputado é proponente.
- **Aprovados:** já aprovados na Câmara (aguardando Senado ou sanção) ou que viraram lei. **Viraram lei:** "Transformado em Norma Jurídica".
- **Presença e faltas:** sessões deliberativas do plenário, desde que o deputado aparece nos dados. Ausência justificada não é separada pela base.
- **Participação nas votações:** votações nominais com voto registrado.

## Se algo der errado

O script termina com erro se os dados vierem incompletos (poucos deputados, projetos, sessões ou votações). Nesse caso o workflow:

1. falha (o GitHub avisa por e-mail quem é dono do repositório, se as notificações do Actions estiverem ligadas);
2. abre uma **issue** automática com o link do log;
3. manda um **push no celular** via [ntfy.sh](https://ntfy.sh), se o segredo `NTFY_TOPIC` estiver configurado.

Mesmo sem nada disso, o painel mostra um **aviso vermelho** quando os dados têm mais de 3 dias.

### Configurar o aviso no celular (opcional, 2 minutos)

1. Instale o app **ntfy** e assine um tópico com um nome difícil de adivinhar, por exemplo `monitor-deputados-x7k2q9`.
2. No GitHub: *Settings → Secrets and variables → Actions → New repository secret*, nome `NTFY_TOPIC`, valor o nome do tópico.

## Rodar localmente

```bash
python atualizar.py              # legislatura inteira
python atualizar.py --anos 2025  # só um ano (teste rápido)
python -m http.server            # abrir http://localhost:8000
```
