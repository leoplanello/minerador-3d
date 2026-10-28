# Minerador 3D

App de desktop para Windows que lê lojas do Mercado Livre, ranqueia os produtos que vendem bem e leva o aprovado até o anúncio: modelo 3D, fatiamento, custo e margem, texto, imagens, vídeo e publicação. Tudo roda no seu computador. Nada é publicado sem um clique seu.

## Instalar

Baixe o `Minerador3D-Setup-<versão>.exe` na [última release](https://github.com/leoplanello/minerador-3d/releases/latest) e execute. A instalação é por usuário e não pede administrador. O Windows pode mostrar um aviso do SmartScreen, porque o instalador não tem assinatura digital.

O app confere sozinho se há versão nova ao abrir e atualiza com um clique. Seus dados ficam em `%LOCALAPPDATA%\Minerador3D\data` e não são tocados na atualização.

Na primeira abertura, um assistente leva você pelos passos: baixar as ferramentas (Bambu Studio, Blender e ffmpeg, direto dos sites oficiais e com conferência de integridade), entrar nas contas pelo Chrome, informar os custos reais e adicionar a primeira loja.

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

## Desenvolvimento

```bash
pip install -r requirements.txt pytest
python scripts/app/desktop.py      # abre o app; do código, os dados ficam na pasta do projeto
python -m pytest tests             # os testes que precisam de Bambu Studio, Blender ou ffmpeg se pulam sozinhos
```

Estrutura: `scripts/app` (servidor, telas em `static/`, fatiamento, imagens, vídeo, atualização), `scripts/mine` (leitura de lojas e busca de modelos), `db/schema.sql` (banco), `build/` (empacotamento), `tests/`.

## Gerar o instalador e publicar uma versão

```bash
pip install pyinstaller
python build/build.py 1.0.0        # precisa do Inno Setup 6 para montar o instalador
```

Para publicar, crie uma tag: `git tag v1.0.0 && git push origin v1.0.0`. O workflow `release.yml` roda os testes, monta o instalador e cria a release com o arquivo `.sha256` que o app confere antes de instalar uma atualização.
