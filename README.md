# Minerador 3D

App de desktop para Windows que lê lojas do Mercado Livre, ranqueia os produtos que vendem bem e leva o aprovado até o anúncio: modelo 3D, fatiamento, custo e margem, texto, imagens, vídeo e publicação. Tudo roda no seu computador. Nada é publicado sem um clique seu.

## Instalar

Baixe o `Minerador3D-Setup-<versão>.exe` na [última release](https://github.com/leoplanello/minerador-3d/releases/latest) e execute. A instalação é por usuário e não pede administrador. O Windows pode mostrar um aviso do SmartScreen, porque o instalador não tem assinatura digital.

O app confere sozinho se há versão nova ao abrir e atualiza com um clique. Seus dados ficam em `%LOCALAPPDATA%\Minerador3D\data` e não são tocados na atualização.

Na primeira abertura o app baixa sozinho, em segundo plano, o Bambu Studio, o Blender e o ffmpeg (direto dos sites oficiais, com conferência de integridade, retomando se a conexão cair); uma faixa no topo mostra o andamento. Se uma etapa precisar de uma ferramenta que ainda não chegou, ela espera a instalação em vez de falhar. Um assistente leva você pelos demais passos: entrar nas contas pelo Chrome, informar os custos reais e adicionar a primeira loja. O Chrome e o login do Claude precisam ser feitos por você; o app avisa quando faltam.

## O que o app faz

- **Lojas:** lê os anúncios mais vendidos de lojas do Mercado Livre com o Chrome, um por vez, parando no captcha ou no login para você resolver.
- **Produtos:** ranking por vendas, avaliações, crescimento e preço, em lista ou grade. Você aprova ou descarta.
- **Produção:** busca o modelo no Printables, MakerWorld e Thingiverse (com a licença à vista), fatia no Bambu Studio (perfil A1), calcula custo e margem, escreve o texto com o Claude, gera imagens no Blender (foto de estúdio em fundo branco e vistas "em uso", com a peça na parede ou na mesa) e monta o vídeo com o ffmpeg. Imagens e vídeo têm opções detalhadas.
- **Seleção:** filtros do que você aceita imprimir (impressora e volume, tempo máximo, fragilidade, suporte por fatiamento de teste, cores, montagem, estoque de filamento), vendas por dia pela idade do anúncio, tese do produto (dor, faixa de preço, similares), famílias de produtos, funil de abrir (5 a 10) e fechar (3 a 5) com o desempenho depois de publicado, margem ao preço do concorrente e fluxo de foto real da amostra impressa.
- **Resumo:** tudo o que foi feito num lugar só, com simulação de lucro mensal.
- **Publicação:** Mercado Livre pela API oficial. Na Shopee não há automação (a Shopee bloqueia navegador controlado por programa): o app prepara o kit e você cadastra pela Central do Vendedor.

## O que depende de você

- Custos reais em Configurações (os iniciais são estimativas).
- Texto por Claude: rode `claude` uma vez num terminal e digite `/login`.
- Mercado Livre: crie o app em developers.mercadolivre.com.br e salve o App ID e a Secret Key em Configurações.
- Vídeo: grave a voz do roteiro e envie o áudio (sem áudio o vídeo sai mudo, só com legenda).

## Sala virtual: estúdio e vídeo em 360°

Na sala virtual (cartão "Sala virtual") há dois ambientes principais e um vídeo de volta completa:

- **Estúdio**: fundo liso em tigela (sem quina de horizonte), luz de cima mais seis laterais em anel (a parede curva fica com o mesmo brilho em todo o giro), sombra de contato, oclusão ambiente e profundidade de campo leve. A câmera dá a volta completa de 360° em torno da peça.
- **Sala com a peça em mesa ou chão**: a câmera fica parada e a peça gira 360° sobre a própria base (a parede ocupa o outro lado da câmera, então a câmera não pode dar a volta).
- **Sala com a peça na parede ou prateleira**: continua o arco de meia volta de antes (uma volta completa atravessaria a parede).

O vídeo padrão tem 8 s e 24 quadros/s e fecha em loop: o último quadro encosta no primeiro sem tranco (a diferença entre eles é igual à de dois quadros seguidos). O padrão renderiza em 720×1280 e o ffmpeg amplia para 1080×1920; a opção "Alta qualidade" renderiza direto em 1080×1920 com mais amostras.

**Tempos medidos** (i5-1135G7, sem GPU NVIDIA, EEVEE; Blender 4.2.3 LTS; 192 quadros = 8 s; cada execução inclui cerca de 15 s de abertura do Blender):

| Vídeo | Resolução de render | Tempo total | Por quadro |
|---|---|---|---|
| Estúdio, padrão (medido em 07/11, versão com sombra de contato e peça maior) | 720×1280 | 538 s (~9 min) | 2,8 s |
| Estúdio, padrão (medido antes das correções de luz e sombra) | 720×1280 | 311 s (~5 min) | 1,6 s |
| Sala com peça girando, padrão (mesa de escritório, medido em 07/11) | 720×1280 | 431 s (~7 min) | 2,2 s |
| Sala com peça girando, padrão (sala com armário, medido antes) | 720×1280 | 281 s (~5 min) | 1,5 s |
| Estúdio, padrão (medido antes, com outros testes rodando ao mesmo tempo) | 1080×1920 | 600 s | 3,1 s |
| Sala com peça girando, padrão (idem) | 1080×1920 | 577 s | 3,0 s |
| Estúdio, alta qualidade | 1080×1920 | 1161 s (~19 min) | 6,1 s |

Cycles não foi medido (no i5-1135G7 só CPU, é muito mais lento); fica como opção e a tela avisa.

Não há imagem final em Cycles medida aqui. A pré-visualização (EEVEE 640 px) leva cerca de 11 s.

## Desenvolvimento

```bash
pip install -r requirements.txt pytest
python scripts/app/desktop.py      # abre o app; do código, os dados ficam na pasta do projeto
python -m pytest tests             # os testes que precisam de Bambu Studio, Blender ou ffmpeg se pulam sozinhos
```

Estrutura: `scripts/app` (servidor, telas em `static/`, fatiamento, imagens, vídeo, atualização), `scripts/mine` (leitura de lojas e busca de modelos), `db/schema.sql` (banco), `build/` (empacotamento), `tests/`.

## Notas da versão 1.4.0

- **Salas 3D importadas: em teste.** Ainda não estão prontas para uso. A sala importada do escritório sai com materiais cinza (materiais Corona não ligados) e o apartamento de 1,6 GB ainda não foi testado. Use as salas padrão até a próxima versão.

## Gerar o instalador e publicar uma versão

```bash
pip install pyinstaller
python build/build.py 1.0.0        # precisa do Inno Setup 6 para montar o instalador
```

Para publicar, crie uma tag: `git tag v1.0.0 && git push origin v1.0.0`. O workflow `release.yml` roda os testes, monta o instalador e cria a release com o arquivo `.sha256` que o app confere antes de instalar uma atualização.
