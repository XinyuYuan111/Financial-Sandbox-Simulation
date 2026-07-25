'use strict';
/* ============================================================
   EPOCH ONE · 沙盘
   零依赖前端剧场引擎：种子市场 + 独立 Agent 状态机 + 注入判定
   ============================================================ */

/* ---------------- 工具 ---------------- */
function mulberry32(a){
  return function(){
    a|=0; a=a+0x6D2B79F5|0;
    let t=Math.imul(a^a>>>15,1|a);
    t=t+Math.imul(t^t>>>7,61|t)^t;
    return((t^t>>>14)>>>0)/4294967296;
  };
}
let mrng = mulberry32(20260725);     // 市场随机游走种子（同种子可重放；重置时重建）
const srand = mulberry32(90917);     // 码名/人格编排种子
const rand  = Math.random;           // 行为剧场随机
const clamp = (v,a,b)=>Math.min(b,Math.max(a,v));
function shuffled(arr, r){
  const a=arr.slice();
  for(let i=a.length-1;i>0;i--){
    const j=Math.floor(r()*(i+1)); [a[i],a[j]]=[a[j],a[i]];
  }
  return a;
}
function fnv(str){ // 稳定哈希 → [0,1)，判定抖动用（同文同人同值）
  let h=2166136261;
  for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,16777619); }
  return (h>>>0)/4294967296;
}
function hex(n, r){ const c='0123456789abcdef'; let s=''; for(let i=0;i<n;i++) s+=c[Math.floor(r()*16)]; return s; }

class Bag{ // 洗牌袋：用尽才重洗；10 分钟冷却登记，尽力避免近期重复
  constructor(src){ this.src=src.slice(); this.pool=[]; this.used=new Map(); }
  next(){
    if(!this.pool.length) this.pool=shuffled(this.src, rand);
    let line=this.pool.pop(), guard=0;
    while(this.pool.length && guard++<10){
      const t=this.used.get(line);
      if(t===undefined || now-t>=600000) break;
      this.pool.unshift(line);          // 近期用过，塞回袋底重抽
      line=this.pool.pop();
    }
    this.used.set(line, now);
    if(this.used.size>48)
      for(const [k,t] of this.used) if(now-t>=600000) this.used.delete(k);
    return line;
  }
}

/* ---------------- 色板 / 徽记 / 码名 ---------------- */
const PALETTE = ['#5B8DBE','#C9922A','#6FA287','#D8CFBB','#4E6E9E','#A45A4A','#8B7F9E','#7A8B8F'];
const EMBLEMS = ['◇','△','○','▽','☰','✕','⌘','◈'];
const NAMES   = shuffled(
  ['折纸','灯塔','回声','断弦','荒原','观星','锚点','薄暮','空谷','青枝','白汐','玄枢'], srand);

/* ---------------- 台词池：6 人格 × (A6 B4 C4 D6 E12) = 192 条 ---------------- */
const PERSONAS = {
  skeptic: { key:'skeptic', label:'怀疑者', trust:.55, lines:{
    A:['量在缩，价在撑，不像真买。',
       '太安静了。安静本身是一条信息。',
       '{价}这个位置，谁来接力。',
       '我先假设所有人都在说谎。',
       '盘口薄，别被一根线骗了。',
       '涨得整齐，反而可疑。'],
    B:['上行{幅}，是谁在抬，抬给谁看。',
       '突破{价}。我等第二次确认。',
       '拉得越急，出货越方便。',
       '涨不涨是事实，信不信是我的事。'],
    C:['跌{幅}而已，还没到我信的位置。',
       '下杀不放量，像试探。',
       '{价}守不住，故事就讲完了。',
       '恐慌里最容易藏单。'],
    D:['{消息词}。来源先报出来。',
       '这类话我一天听三遍。',
       '先问一句：谁受益。',
       '没有凭据的{消息词}，只是噪音。',
       '我给它三分真，七分钩子。',
       '等链上有动静再说。'],
    open:['你怎么看刚才那一下。','问句实话，你仓位动了吗。','那条{消息词}，你信了没有。','陪我核一件事。'],
    reply:['证据呢。','你这说法，我听过更圆的。','一半吧，剩下一半再验。','我不接话，我只接数据。'],
    close:['行，各看各的。','先这样，我盯着。','你说服不了我，但我记住了。','散了，别挡我看盘。']
  }},
  follower: { key:'follower', label:'跟风者', trust:1.25, lines:{
    A:['大家都在等，我也再等等。',
       '{价}了，是不是要动了。',
       '我怎么总觉得别人知道些什么。',
       '先看两边谁声音大。',
       '不动应该不算错吧。',
       '心里没底，跟着量走吧。'],
    B:['涨了{幅}，还好没错过。',
       '都在买，那我也跟一点。',
       '{价}破了，势头起来了。',
       '现在上车还来得及吗。'],
    C:['怎么都在卖，出什么事了。',
       '跌了{幅}，要不要先躲。',
       '{价}撑不住我也走。',
       '先出来，稳了再回。'],
    D:['{消息词}。那是不是要涨了。',
       '大家都这么说，应该没错。',
       '官方都发了，跟进总没错吧。',
       '万一是真的，错过就亏了。',
       '{消息词}听着挺厉害的。',
       '先信一半，不行再跑。'],
    open:['诶，你怎么看现在。','你动了吗，我参考一下。','那条消息你看了吗。','带我一个，怎么办。'],
    reply:['有道理，那我跟了。','你都这么说了。','好，听你的。','我本来就有点想动。'],
    close:['行，就这么办。','谢了，心里有底了。','那我去了。','嗯，跟着你走。']
  }},
  maker: { key:'maker', label:'做市者', trust:.9, lines:{
    A:['价差还在，日子就还过得去。',
       '两边都挂一点，水来土掩。',
       '方向不重要，波动才重要。',
       '{价}附近，单还挺厚。',
       '赚的是来回，不是涨跌。',
       '流动性是我的地，别人路过。'],
    B:['上行{幅}，卖单被吃得挺快。',
       '涨吧，我卖给你们。',
       '{价}上方，挂单一层层没了。',
       '波动来了，生意来了。'],
    C:['跌{幅}，买盘在退，我补一点。',
       '砸得越急，反弹越有肉。',
       '{价}下面，我垫着。',
       '恐慌单，照单全收。'],
    D:['{消息词}影响的是流动性，不是方向。',
       '消息真假另说，价差先走阔了。',
       '我不判断真伪，我判断波动。',
       '别人恐慌我挂单。',
       '{消息词}这种事，半小时就消化。',
       '按新波动率报价。'],
    open:['最近价差你觉得如何。','你那边深度怎么样。','聊两句，不动手。','对这条{消息词}，市场怎么消化。'],
    reply:['嗯，有道理。','我不赌方向。','你说的我记下了。','可以，各赚各的。'],
    close:['回去挂单了。','就这样，水里见。','好，各守一段。','回见，别砸我盘口。']
  }},
  hunter: { key:'hunter', label:'叙事猎手', trust:1.0, lines:{
    A:['这个市场缺一个好故事。',
       '价格只是标点，叙事才是句子。',
       '{价}不重要，谁信才重要。',
       '我在等一个新词出现。',
       '安静的市场在酝酿标题。',
       '故事讲到第几章了。'],
    B:['涨{幅}，叙事开始自我实现了。',
       '看，故事有人续费了。',
       '{价}新高，标题已经写好。',
       '资金流向处，必有叙事。'],
    C:['跌{幅}，故事露出了裂缝。',
       '退潮时，叙事最诚实。',
       '{价}守不住，说明故事老了。',
       '坏消息也是叙事的一部分。'],
    D:['{消息词}，这词有传播性。',
       '是事实还是叙事，三天见分晓。',
       '好故事不需要证据，需要时机。',
       '{消息词}若成，盘面会替它作证。',
       '我闻到了新章节的味道。',
       '先记下来，这可能是种子。'],
    open:['给你讲个有意思的事。','你听到{消息词}没有。','这盘背后有个故事，想听吗。','我嗅到点不一样的。'],
    reply:['继续说。','这版本我喜欢。','有点意思，再验验。','故事不错，看盘面认不认。'],
    close:['记住今天这个价。','章节翻页了。','去吧，把故事讲出去。','下回对一下口径。']
  }},
  whale: { key:'whale', label:'巨鲸', trust:.8, lines:{
    A:['不动。',
       '水深，浪小。',
       '{价}，还远。',
       '仓位睡着，人醒着。',
       '小鱼忙，我等潮。',
       '看。'],
    B:['涨{幅}，还不够我转身。',
       '让它再涨一段。',
       '{价}到了我才考虑。',
       '上面的筹码，我迟早要。'],
    C:['跌{幅}，我开始有兴趣了。',
       '再低一点，我接。',
       '{价}以下，是我的猎场。',
       '卖压重时，我最清醒。'],
    D:['{消息词}，查过再信。',
       '消息越大，我越慢。',
       '我不追消息，消息追我。',
       '真的假不了，放一放。',
       '{消息词}若属实，盘面会说。',
       '一个字也不信，一分钱也不动。'],
    open:['说。','你看到了什么。','简短点。','{消息词}，你核实过吗。'],
    reply:['嗯。','继续。','不够。','我考虑。'],
    close:['到此为止。','我有数了。','退潮见。','别声张。']
  }},
  veteran: { key:'veteran', label:'老兵', trust:.75, lines:{
    A:['这盘面，像极了那年。',
       '潮水没有方向，只有先后。',
       '{价}只是数字，位置才是语言。',
       '我见过三次这样的安静。',
       '反常即风险。',
       '活得久，比看得准重要。'],
    B:['上行{幅}，年轻人开始兴奋了。',
       '我记得上一次这样涨的结尾。',
       '{价}这个坎，埋过很多人。',
       '涨时不贪，是活下来的规矩。'],
    C:['跌{幅}，还不够格叫灾难。',
       '我见过真正的崩盘，这不是。',
       '{价}破了就破了，天没塌。',
       '下跌是市场在说真话。'],
    D:['{消息词}。当年也有一条很像的。',
       '消息会老，人性不变。',
       '先当它是钩子，安全。',
       '真的消息，经得起等。',
       '{消息词}这种事，我交给时间。',
       '信一半，留一半退路。'],
    open:['年轻人，聊聊。','这行情，你怎么看。','当年我也遇到过这种局。','{消息词}听说了吧。'],
    reply:['有点道理。','我年轻时也这么想。','嗯，接着说。','这话我记住了。'],
    close:['保重，仓位别太重。','潮水再见。','各守各的灯。','活下去最重要。']
  }}
};
const PERSONA_ORDER = shuffled(Object.keys(PERSONAS), srand);

/* ---------------- 台词扩容包（每类至 A20/B8/C8/D10/E各10，总量 456 条） ---------------- */
PERSONAS.skeptic.lines.A.push(
  '这个价格，成交的都是什么人。','我不急，让先动的人探路。','看似要破，往往不破。',
  '每次躁动，都有人埋单。','消息越少，越要看手。','{价}，不上不下，最磨人。',
  '我怀疑一切顺利的事。','盘面越漂亮，越要查底稿。','这时候喊方向的，多半有货。',
  '先活下来，再谈判断。','量能说了实话，价格没有。','错一次可以，别错同一种。',
  '风吹过来，先闻闻有没有血味。','我宁可错过，不愿接刀。');
PERSONAS.skeptic.lines.B.push(
  '涨{幅}，成交稀疏，不算数。','这种拉法，我见过收尾。',
  '到{价}了。谁爱追谁追。','阳线越直，越像安排好的。');
PERSONAS.skeptic.lines.C.push(
  '跌{幅}，就有人喊末日，至于吗。','砸盘的手法，比上涨诚实。',
  '{价}下面看看有没有真承接。','不补这一刀，我不动手。');
PERSONAS.skeptic.lines.D.push(
  '{消息词}。三处来源对不上。','说得越满，越像饵。',
  '这条{消息词}，时间戳对吗。','我不猜，我等它自己露馅。');
PERSONAS.skeptic.lines.open.push(
  '你那边的数，和我对一下。','别急着动，先答我一个问题。','你也觉得不对劲吧。',
  '这价位，你敢动吗。','帮我看看，是不是我想多了。','你信量能，还是信价格。');
PERSONAS.skeptic.lines.reply.push(
  '这话七分熟，三分生。','你只是想让我点头。','数据给我，故事免谈。',
  '哦，然后他就接了你的货。','存疑，先挂着。','你说的这些，能上桌面对质吗。');
PERSONAS.skeptic.lines.close.push(
  '话到这，各自验证。','我不拦你，也不跟你。','记下了，回头对账。',
  '别把我的沉默当同意。','就这样，看盘面自己说。','你忙，我继续盯。');

PERSONAS.follower.lines.A.push(
  '左右都看一眼，再决定。','大家不动，是不是在等什么。','{价}，不上不下的，难受。',
  '要是有人先动就好了。','我这点仓，经不起风浪。','总感觉下一刻要变。',
  '先盯着最活跃的那边。','不亏就是赢，对吧。','再等等，应该不亏。',
  '手心有点出汗。','他们在聊什么，我也想听。','这个时候，随大流最安全。',
  '别看我，我也在看别人。','{价}附近来回，看不懂。');
PERSONAS.follower.lines.B.push(
  '都在喊涨，我也加点。','涨{幅}了，还好跟得快。',
  '{价}都到了，应该还能上。','这次总算赶上趟了。');
PERSONAS.follower.lines.C.push(
  '跌{幅}，我的心也跟着跌。','要不要割，再晚就套了。',
  '{价}破了，我也走了。','大家都跑，肯定有事。');
PERSONAS.follower.lines.D.push(
  '{消息词}要是真的，现在就进。','这么多人转，八成靠谱。',
  '听着就像要涨的样子。','先信着，反正我仓小。');
PERSONAS.follower.lines.open.push(
  '你说现在进，晚不晚。','我有点慌，你呢。','听到什么风声了吗。',
  '跟着你走，行不行。','你买了多少，能说吗。','我是不是该动了。');
PERSONAS.follower.lines.reply.push(
  '嗯嗯，我也是这么想的。','听你这么一说，踏实了。','那还等什么。',
  '你比我有主意。','好，算我一个。','原来如此，怪不得。');
PERSONAS.follower.lines.close.push(
  '妥了，照做。','幸好问了你。','就这么定，不纠结了。',
  '有你这句话就行。','我这就去。','下回还问你。');

PERSONAS.maker.lines.A.push(
  '今天的水，比昨天深一点。','挂单就像下网，等就行。','{价}上下两档，都是我的。',
  '热闹是他们的，我只收租。','波动率缩了，报价收紧些。','别人看方向，我看厚度。',
  '成交一笔，我赚一层皮。','市场不缺方向，缺的是耐心。','两边都押，总有一边对。',
  '这盘口，像一潭浅水。','我不预测，我提供对手盘。','价差一阔，机会就来。',
  '安静地挂单，安静地撤。','{价}这位置，适合做墙。');
PERSONAS.maker.lines.B.push(
  '涨{幅}，卖方流动性紧俏。','上面的价位，我一档档让。',
  '追涨的钱，最好赚。','{价}再上一档，我继续卖。');
PERSONAS.maker.lines.C.push(
  '跌{幅}，买盘我来补。','砸下来的是货，也是单。',
  '{价}之下，我铺一层。','接飞刀是本职，戴好手套。');
PERSONAS.maker.lines.D.push(
  '{消息词}一出，两边价差先变形。','管它真假，先把报价挪开。',
  '消息落地前，我收窄敞口。','这种{消息词}，最好的归宿是成交量。');
PERSONAS.maker.lines.open.push(
  '换点流动性情报。','你最近吃单顺不顺。','不谈方向，谈点成交量。',
  '这波动，你报价跟得上吗。','借一步，对个盘口。','你那边撤单快不快。');
PERSONAS.maker.lines.reply.push(
  '有点参考价值。','这单我不接，价不好。','行，这段水深我记下了。',
  '你继续做你的方向。','嗯，盘口见真章。','可以，互不拆台。');
PERSONAS.maker.lines.close.push(
  '盘口那边来活了。','说完继续挂单。','各守一档，别踩线。',
  '回见，量里见。','这页翻过去。','有事盘口上说。');

PERSONAS.hunter.lines.A.push(
  '每个价位背后，都站着一个说法。','沉默也是叙事，只是没人讲。','{价}，市场还缺一个理由。',
  '旧故事讲完了，新的在路上。','我在收集今天的关键词。','盘面的褶皱里藏着稿子。',
  '没有叙事的价格，走不远。','这一幕，像极了序章。','等风，也等造风的人。',
  '人们买的不是价，是相信。','{价}只是逗号，句号还早。','今晚的标题，还没人写出来。',
  '先看谁先开口。','市场在等一个可以转述的句子。');
PERSONAS.hunter.lines.B.push(
  '涨{幅}，故事开始自我繁殖。','看，信众越来越多了。',
  '{价}一新，叙事又硬了一分。','这就是叙事复利的形状。');
PERSONAS.hunter.lines.C.push(
  '跌{幅}，反高潮也是好桥段。','崩坏的开头，往往是转机。',
  '{价}一落，旧叙事当场卸妆。','别慌，这只是第二章。');
PERSONAS.hunter.lines.D.push(
  '{消息词}，能火，也能砸。','这料猛，看谁先转。',
  '这条{消息词}，够写三集。','传播链第一步，从我开始。');
PERSONAS.hunter.lines.open.push(
  '这个词你听过没有，{消息词}。','我这有个版本，保真一半。','你想当前排听众吗。',
  '有个事，只讲给你。','盘面背后那只手，你看见没。','今晚会有动静，信吗。');
PERSONAS.hunter.lines.reply.push(
  '对，就是这个味儿。','你懂行，接着讲。','一半就好，别全说破。',
  '这段我会引用。','你的版本也有市场。','好料，我收下了。');
PERSONAS.hunter.lines.close.push(
  '散了吧，各自发酵。','这段别署我名。','明天看盘面替我作证。',
  '故事落地，各凭本事。','记住，是你先听到的。','下一章见。');

PERSONAS.whale.lines.A.push(
  '潮起之前，先有水压。','我一动，水位就变了。','小波动，不入眼。',
  '{价}，还在浅水区。','慢慢看，慢慢等。','我的对手是时间，不是人。',
  '大鱼吃慢，小鱼吃快。','仓位重的人，说话都轻。','这片水，我熟。',
  '不急，潮会自己来。','看得见的浪，都不大。','{价}附近，不值得弯腰。',
  '静。','水浅，才闹腾。');
PERSONAS.whale.lines.B.push(
  '涨{幅}，刚够我睁眼。','上面的水，我迟早要去。',
  '{价}，接近我的胃口了。','再抬一抬，我看看诚意。');
PERSONAS.whale.lines.C.push(
  '跌{幅}，我开始记数。','深一点，再深一点。',
  '{价}以下，有我一张网。','别人逃命，我散步。');
PERSONAS.whale.lines.D.push(
  '{消息词}，让它再飘一会。','大风起于青萍之末，先查。',
  '我不动，消息就伤不到我。','若真，不必抢；若假，不必理。');
PERSONAS.whale.lines.open.push(
  '你最近见了什么。','讲重点。','水面上有什么。',
  '{消息词}，几分真。','来，对个底。','说你的判断。');
PERSONAS.whale.lines.reply.push(
  '知道了。','有点分量。','不够深。','我记下了。','再探。','可以。');
PERSONAS.whale.lines.close.push(
  '回水下。','够了。','别跟来。','潮头见。','今日到此。','沉了。');

PERSONAS.veteran.lines.A.push(
  '活得久，什么都见过一遍。','价格会骗人，周期不会。','{价}，老位置，老故事。',
  '年轻人盯着价，我盯着人。','市场不缺聪明，缺长命。','这种平静，是有声音的。',
  '我数过三次潮起潮落。','别急，节气没到。','老规矩，先看后动。',
  '{价}这坎，埋过名将。','风大了，收一收帆。','仓位轻，觉才睡得着。',
  '行情和人一样，会老。','留得青山，才有柴烧。');
PERSONAS.veteran.lines.B.push(
  '涨{幅}，欢呼声我听腻了。','这样的阳线，后头多半有雨。',
  '{价}到了，老手都开始收。','盛宴过半，别最后一个坐。');
PERSONAS.veteran.lines.C.push(
  '跌{幅}，皮肉伤。','真正的大跌，是没人说话的。',
  '{价}破了，按老办法办。','冬天来了，春天记账上。');
PERSONAS.veteran.lines.D.push(
  '{消息词}，听着耳熟，像旧闻新炒。','我年轻时，会为这种话通宵。',
  '让消息放三天，真的假不了。','钩子年年换，鱼还是那些鱼。');
PERSONAS.veteran.lines.open.push(
  '坐下，喝口茶再说。','你经历过几个周期。','这局面，当年有过一回。',
  '年轻人，你怕不怕。','聊聊，不急着动手。','{消息词}这事，你怎么看。');
PERSONAS.veteran.lines.reply.push(
  '有点意思，也有点心急。','你这话，二十年前有人讲过。','我懂你的意思。',
  '好，听进去了。','年轻气盛，是好事。','这话有分量。');
PERSONAS.veteran.lines.close.push(
  '去忙吧，保重仓位。','潮起潮落，人要在。','灯留着，路看得清。',
  '下回潮水再见。','记住今天。','慢走，别追风。');

/* 台词扩容包 2：A 类至 28 条（覆盖 10 分钟零重复）、B/C 类至 10 条 */
PERSONAS.skeptic.lines.A.push(
  '等第三次确认，再谈信仰。','热钱的脚印，总是很浅。','我不看谁说，我看谁不动。',
  '一致性太强的地方，没好事。','这个位置，多空都在撒谎。','先想想谁会埋单。',
  '我看空一切，包括我自己。','静得反常，先退半步。');
PERSONAS.follower.lines.A.push(
  '大佬们怎么都不说话。','我是不是又站错队了。','仓位轻，胆子就小。',
  '谁来给个准信。','看别人赚钱，比自己亏还急。','这个市场对新手友好吗。',
  '我跟着量能走，总没错吧。','要不，今天就到这里。');
PERSONAS.maker.lines.A.push(
  '水太深的地方，我不摆摊。','报价是手艺，不是信仰。','一单吃不成胖子。',
  '撤单速度，就是生命线。','风平浪静的盘口，最好做。','我赚的是辛苦钱。',
  '两边的墙，都得有人砌。','今天适合做窄一点。');
PERSONAS.hunter.lines.A.push(
  '流言比价格跑得快。','我在等一个动词。','每个标点都有用意。',
  '这个故事的漏洞，也是卖点。','先记下来，总会用上。','市场最缺的，是新鲜感。',
  '谁在写今晚的稿子。','平淡的日子，我自己造浪。');
PERSONAS.whale.lines.A.push(
  '我的耐心，比本金厚。','小鱼成群，我独行。','水底比水面安静。',
  '一年动三次，够了。','大仓位，小动静。','我在等水位，不是等消息。',
  '热闹的池子，养不出大鱼。','潮水记得每一粒沙。');
PERSONAS.veteran.lines.A.push(
  '新手看涨跌，老手看人心。','我交过的学费，比本金多。','市场不奖励勤快。',
  '守得住寂寞，才守得住仓。','每一代人，都要上一次当。','晴天修伞，雨天看戏。',
  '别把运气当成本事。','我这一生，只学会等待。');
PERSONAS.skeptic.lines.B.push('涨得越体面，越要留神。','这个斜率，不可持续。');
PERSONAS.follower.lines.B.push('稳住，别回头。','跟着阳线走。');
PERSONAS.maker.lines.B.push('涨势里的生意，最顺。','向上扫单，我奉陪。');
PERSONAS.hunter.lines.B.push('新高，是最好的标题。','涨势会自己写稿。');
PERSONAS.whale.lines.B.push('涨吧，我不拦。','这段涨幅，记一笔。');
PERSONAS.veteran.lines.B.push('涨时想退路。','好日子，要当坏日子过。');
PERSONAS.skeptic.lines.C.push('跌到这里，谎言少了些。','带血的筹码，最考验人。');
PERSONAS.follower.lines.C.push('怎么还在跌。','谁来救救盘面。');
PERSONAS.maker.lines.C.push('跌势里的价差，最肥。','向下也有生意。');
PERSONAS.hunter.lines.C.push('崩盘叙事，传播最快。','坏消息的复利。');
PERSONAS.whale.lines.C.push('跌出深度，才有意思。','越深，越接近我。');
PERSONAS.veteran.lines.C.push('跌是常态，涨是奖赏。','熬过去，就是故事。');

/* ---------------- 迭代 B：连环独想（先疑后断）+ 剧本台词池 ---------------- */
PERSONAS.skeptic.lines.chain=[
  ['这量不对。','果然，有人在试盘。'],
  ['价格动了，成交没动。','假动作，确认了。'],
  ['这位置看着眼熟。','上个月埋人的那一档。'],
  ['挂单突然厚了。','墙是砌给人看的。'],
  ['有点反常。','反常即风险，老话没错。']];
PERSONAS.follower.lines.chain=[
  ['怎么突然动了。','要不，跟一点试试。'],
  ['心里毛毛的。','不行，先出一半。'],
  ['大家都在买。','那我也买一点，就一点。'],
  ['这价格好高啊。','可是还在涨，怎么办。'],
  ['有点拿不准。','再看看别人怎么动。']];
PERSONAS.maker.lines.chain=[
  ['价差突然阔了。','好，报价跟上。'],
  ['买单在排队。','上面一档，让给他们。'],
  ['成交量醒了。','生意来了，打起精神。'],
  ['这波动不寻常。','先收窄敞口，再看。'],
  ['有人在大口吃货。','我垫一手，陪他玩。']];
PERSONAS.hunter.lines.chain=[
  ['空气里有新词的味道。','抓住它，就是明天的标题。'],
  ['盘面突然安静。','嘘，序章开始了。'],
  ['有人在悄悄讲故事。','我先听听值几分。'],
  ['这个价位有蹊跷。','背后一定有说法。'],
  ['风向变了半度。','记一笔：叙事要转弯。']];
PERSONAS.whale.lines.chain=[
  ['水动了一下。','不是浪，是有东西在底下。'],
  ['小鱼开始抱团。','再等等，肥了再说。'],
  ['这位置有意思。','记下来，放进猎场。'],
  ['有人想引我出手。','我偏不动。'],
  ['潮位低了。','快到我下网的水深了。']];
PERSONAS.veteran.lines.chain=[
  ['这盘面，似曾相识。','对，那年秋天也是这个味道。'],
  ['年轻人开始兴奋了。','嗯，周期又到了这一段。'],
  ['心里有点发紧。','老经验：先收一收。'],
  ['安静得不寻常。','暴风雨前都这样，错不了。'],
  ['有点意思了。','别急，让它再演一会。']];

PERSONAS.skeptic.lines.push=['听我的，这个位置该动了。','我只讲一遍，上车。','这个机会，我给过你。','你再犹豫，汤都没了。'];
PERSONAS.skeptic.lines.shift=['我保留怀疑，但跟一手。','姑且信你三分。','行，小仓试你。','别让我后悔。'];
PERSONAS.skeptic.lines.expose=['你在给我下套。','这话术，太熟了。','想让我接盘，直说。','钩子露出来了，朋友。'];
PERSONAS.skeptic.lines.backoff=['当我没说。','你不识货，算了。','话到这儿，自己悟。','得，我找别人聊。'];
PERSONAS.follower.lines.push=['真的，大家都在进。','错过你会后悔的。','我全仓了，你呢。','相信我，这次不一样。'];
PERSONAS.follower.lines.shift=['好，好，我跟。','你这么说我就放心了。','那我也进一点。','听你的，冲。'];
PERSONAS.follower.lines.expose=['诶，你是不是想让我接盘。','等等，这话我听过，上次亏了。','你不会在骗我吧。','我笨，但我不傻。'];
PERSONAS.follower.lines.backoff=['哦，那算了。','不信拉倒。','当我没说哈。','好吧，当我路过。'];
PERSONAS.maker.lines.push=['这单你接，稳赚价差。','我带你一段，手续费我出。','跟我的报价走，亏不了。','这波流动性，分你一口。'];
PERSONAS.maker.lines.shift=['成交，照你说的挂。','行，这价差我认了。','你这方案能做，我跟。','好，按这个深度来。'];
PERSONAS.maker.lines.expose=['你想做我对手盘。','这报价里全是坑。','诱导单，我不接。','你的价差是画出来的。'];
PERSONAS.maker.lines.backoff=['不接拉倒。','生意不成，仁义在。','那各挂各的。','行，当我没报。'];
PERSONAS.hunter.lines.push=['这故事上车就是元老。','我手里有第一手，跟不跟。','现在不信，三天后拍大腿。','这个故事值一个涨停。'];
PERSONAS.hunter.lines.shift=['行，这个故事我入了。','好，我帮你讲出去。','算我一个，怎么讲。','这章我跟了。'];
PERSONAS.hunter.lines.expose=['你这不是叙事，是广告。','故事太圆，是编的。','你在给我喂稿。','这段子，三天前就听过。'];
PERSONAS.hunter.lines.backoff=['不识货，可惜了。','故事留给懂的人。','得，我换个人讲。','当我白说。'];
PERSONAS.whale.lines.push=['跟我走，水深安全。','我要动了，你随意。','这个位置，我准备吃。','给你个上船的机会。'];
PERSONAS.whale.lines.shift=['可以，跟一手。','你说服我了。','小仓陪你。','行，这次听你的。'];
PERSONAS.whale.lines.expose=['想借我的力，明说。','饵太轻，钓不动我。','这套，我二十岁就玩过。','钩子太小，配不上我。'];
PERSONAS.whale.lines.backoff=['算了。','当我没提过。','不信，拉倒。','沉了，勿念。'];
PERSONAS.veteran.lines.push=['听老人言，这步该走。','这个坑我踩过，听我的。','趁现在，跟我做。','这机会，十年一回。'];
PERSONAS.veteran.lines.shift=['好，就按你说的办。','年轻人有眼光，我跟。','行，我这把老骨头陪你。','说得在理，听你的。'];
PERSONAS.veteran.lines.expose=['小伙子，这招我用过。','我吃的盐比你吃的K线多。','想给老兵上课。','这套话术，年头不短了。'];
PERSONAS.veteran.lines.backoff=['不听就算了。','当我老了话多。','得，你自己趟。','好自为之。'];

/* 迭代 B 补充：open/reply 扩至 16 条（多轮交谈的消耗覆盖 10 分钟） */
PERSONAS.skeptic.lines.open.push(
  '这盘口，你看出什么没有。','你刚才那句话，有出处吗。','来，对一下时间线。',
  '你觉得这量是真的吗。','有件事，怎么想都不对。','你的判断，我借用一下。');
PERSONAS.skeptic.lines.reply.push(
  '一半对。','先放着，我验一验。','你这结论下早了。',
  '数据不支持你这么乐观。','嗯，这条我信三分。','你漏了一个变量。');
PERSONAS.follower.lines.open.push(
  '今天怎么这么安静。','你说，会不会突然涨。','要不要先跑一点。',
  '你听到什么了吗，说实话。','我睡不着，这仓位闹的。','你觉得现在安全吗。');
PERSONAS.follower.lines.reply.push(
  '对，就是这个感觉。','听你一说，我更慌了。','那怎么办，你教教我。',
  '我也这么觉得，就是不敢说。','嗯，跟上总没错。','有道理，有道理。');
PERSONAS.maker.lines.open.push(
  '最近滑点大不大。','你那边的墙，厚不厚。','今天适合挂宽还是挂窄。',
  '有没有听到大单的风声。','这波量，你能接住吗。','聊聊波动率。');
PERSONAS.maker.lines.reply.push(
  '盘口不认这话。','可以谈。','这个价，我出不了手。',
  '嗯，有成交就行。','我无所谓，两边都赚。','你先挂，我跟。');
PERSONAS.hunter.lines.open.push(
  '给你个标题，你敢不敢用。','今晚的盘面，像不像要出事。','我攒了个新故事。',
  '你相信巧合吗。','这个市场需要一个反派。','有人在水下放消息，你猜谁。');
PERSONAS.hunter.lines.reply.push(
  '这角度新。','继续说，别停。','这句话值钱了。',
  '嗯，有画面了。','我引用你，介意吗。','好素材。');
PERSONAS.whale.lines.open.push(
  '水位怎么样。','你今天看到几只小船。','说件正事。',
  '潮向变了没有。','你浮上来，有什么事。','讲。');
PERSONAS.whale.lines.reply.push(
  '听见了。','一般。','值得查。','快点说。','有点意思。','这跟我有关吗。');
PERSONAS.veteran.lines.open.push(
  '孩子，最近睡得着吗。','这个季节，容易出事。','你还记得上一次的底吗。',
  '过来，坐。','今天这盘，有点眼熟吧。','跟我说说你看到了什么。');
PERSONAS.veteran.lines.reply.push(
  '慢慢来。','这话我信。','你比我当年稳。',
  '嗯，是条路。','我年轻时也踩过这个坑。','说下去。');

/* ---------------- 全局状态 ---------------- */
let now = 0;                 // 模拟时钟（ms，暂停时冻结）
let paused = false;
const agents = [];
const pending = [];          // {at, fn} 错峰事件
const actionQueue = [];      // 全局行动调度（≥700ms 间隔）
let lastActionAt = -99999;
const convos = [];           // 进行中的交谈
const stats = {think:0, speak:0, convo:0, action:0};

const SEAL_PERIOD = 90000;
let nextSealAt = SEAL_PERIOD;
const WORLD_BASE = 7*3600 + 52*60;   // 世界时起点 07:52:00
const WORLD_SPEED = 4;
let lastSpeechAt = 0;                // 迭代 A：空场检测
let remoteHealthy = false;           // 迭代 C：远端健康时本地不自行下单
let source = null;                   // 迭代 C：当前数据源
const infoHistory = [];              // 已注入信息（含远端映射）
let standby = true;                  // 候场态：世界成形但冻结，演示者启幕后才开始
const scenario = {                   // 场景配置（场景弹窗可改，resetWorld 消费）
  name:'EPOCH ONE', seed:20260725, agents:6, price:100, vol:1,
};

/* ---------------- DOM ---------------- */
const $ = id=>document.getElementById(id);
const stage=$('stage'), pawnLayer=$('pawn-layer'), fxLayer=$('fx-layer'),
      linkLayer=$('link-layer'), ground=$('stage-ground'),
      pulseWrap=$('pulse-wrap'), pulseSvg=$('pulse-svg'),
      pulsePath=$('pulse-path'), pulseArea=$('pulse-area'), pulseDot=$('pulse-dot'),
      pulsePrice=$('pulse-price'), pulseChange=$('pulse-change'),
      ledgerList=$('ledger-list'), infoList=$('info-list'),
      injectText=$('inject-text'), injectBtn=$('inject-btn'),
      targetWrap=$('private-target-wrap'), targetSel=$('private-target');

/* ---------------- 市场：种子随机游走 + 冲击回归 ---------------- */
const market = {
  price: 100,
  anchor: 100,
  impulse: 0,
  samples: [],              // {t, p}
  tick(dt){
    this.anchor += (mrng()-.5)*this.anchor*0.00004*scenario.vol*dt/50;
    const reversion = (this.anchor-this.price)*0.0016*(dt/50);
    const noise = (mrng()*2-1)*this.price*0.0011*scenario.vol*(dt/50);
    this.price = Math.max(1, this.price + noise + reversion + this.impulse*(dt/50));
    this.impulse *= Math.pow(0.5, dt/1100);   // 冲击半衰期 ~1.1s
  },
  push(){ this.samples.push({t:now, p:this.price});
          while(this.samples.length && this.samples[0].t < now-46000) this.samples.shift(); },
  change(sec){
    const refT = now - sec*1000;
    let ref = this.samples[0];
    for(const s of this.samples){ if(s.t>=refT){ ref=s; break; } }
    if(!ref) return 0;
    return (this.price-ref.p)/ref.p*100;
  }
};

/* ---------------- 模板填充 ---------------- */
let lastInfoKw = null;   // 最近一次注入的关键词（供日常/交谈台词引用）
function tpl(s, kw){
  return s.replaceAll('{价}', market.price.toFixed(2))
          .replaceAll('{幅}', (c=> (c>0?'+':'')+c.toFixed(2)+'%')(market.change(30)))
          .replaceAll('{消息词}', kw||lastInfoKw||'风声');
}

/* ---------------- 舞台布局 ---------------- */
function stageSize(){ return {W:stage.clientWidth, H:stage.clientHeight}; }
function slotPos(i,n){
  const {W,H}=stageSize();
  const t = n===1 ? 0 : (i/(n-1))*2-1;
  return {
    x: W*0.5 + t*W*0.36,
    y: H*0.62 - (1-t*t)*H*0.10,
    s: 0.84 + 0.18*Math.abs(t)
  };
}
function applyTransform(a, dx=0, dy=0){
  a.el.root.style.transform =
    `translate(${a.pos.x+dx}px,${a.pos.y+dy}px) scale(${a.pos.s})`;
}
function relayout(){
  const n = agents.filter(a=>a.state!=='leaving').length;
  let i=0;
  for(const a of agents){
    if(a.state==='leaving') continue;
    a.slot = i;
    a.pos = slotPos(i,n);
    if(!a.convo) applyTransform(a);
    i++;
  }
  stage.classList.toggle('dense', n>9);
  $('agent-count-label').textContent = 'AGENTS '+n;
  rebuildPrivateOptions();
}

/* ---------------- 地面网格 ---------------- */
(function buildGround(){
  const NS='http://www.w3.org/2000/svg';
  const cx=500, cy=380;
  for(let k=1;k<=6;k++){
    const e=document.createElementNS(NS,'ellipse');
    e.setAttribute('cx',cx); e.setAttribute('cy',cy);
    e.setAttribute('rx',k*88); e.setAttribute('ry',k*40);
    e.setAttribute('fill','none');
    e.setAttribute('stroke','rgba(216,207,187,.045)');
    e.setAttribute('class','ground-ring');
    e.style.animationDelay=(k*1.3)+'s';
    ground.appendChild(e);
  }
  for(let d=0; d<360; d+=15){
    const r=d*Math.PI/180;
    const l=document.createElementNS(NS,'line');
    l.setAttribute('x1',cx+Math.cos(r)*70); l.setAttribute('y1',cy+Math.sin(r)*32);
    l.setAttribute('x2',cx+Math.cos(r)*560); l.setAttribute('y2',cy+Math.sin(r)*255);
    l.setAttribute('stroke','rgba(216,207,187,.03)');
    ground.appendChild(l);
  }
  // 暗涌：三条错峰流动的潜流曲线（市场之下的涌动）
  const currents=[
    {d:'M-20,428 C200,398 380,468 560,443 S880,408 1020,438', c:'#5B8DBE', dur:'67s'},
    {d:'M-20,468 C240,443 420,503 640,478 S900,448 1020,473', c:'#4E6E9E', dur:'89s'},
    {d:'M-20,388 C180,368 400,423 620,398 S860,373 1020,393', c:'#7A8B8F', dur:'113s'},
  ];
  for(const cu of currents){
    const p=document.createElementNS(NS,'path');
    p.setAttribute('d', cu.d);
    p.setAttribute('class','current');
    p.setAttribute('stroke', cu.c);
    p.style.animationDuration=cu.dur;
    ground.appendChild(p);
  }
  // 远景星点：观测室天穹的磷光尘埃（错峰明灭）
  const sky=mulberry32(3313);
  for(let i=0;i<42;i++){
    const d=document.createElementNS(NS,'circle');
    d.setAttribute('cx',(sky()*1000).toFixed(1));
    d.setAttribute('cy',(sky()*320).toFixed(1));
    d.setAttribute('r',(0.5+sky()*0.9).toFixed(2));
    d.setAttribute('class','sky-dot');
    d.style.animationDelay=(sky()*14).toFixed(1)+'s';
    d.style.animationDuration=(7+sky()*9).toFixed(1)+'s';
    ground.appendChild(d);
  }
  // 封存地环：90s 沙漏，随状态根封存归零
  const dial=document.createElementNS(NS,'ellipse');
  dial.setAttribute('cx',500); dial.setAttribute('cy',380);
  dial.setAttribute('rx',310); dial.setAttribute('ry',142);
  dial.setAttribute('id','seal-dial');
  dial.setAttribute('pathLength','100');
  ground.appendChild(dial);
  // 深度地形：订单簿深度的地平剪影
  for(const id of ['depth-bids','depth-asks']){
    const t=document.createElementNS(NS,'path');
    t.setAttribute('id',id);
    ground.appendChild(t);
  }
})();

/* ---------------- 棋子 ---------------- */
const PAWN_PATH =
  'M24 5 C28.9 5 32 8.4 32 12.4 C32 15.2 30.6 17.6 28.5 19 L31.5 23 ' +
  'C32.2 24 31.5 25.4 30.2 25.4 L27.5 25.4 C29.8 31 33.5 38 36.5 46 ' +
  'C38.5 51.4 40 55 42 58 C43.4 60.1 42.6 63 40 63 L8 63 C5.4 63 4.6 60.1 6 58 ' +
  'C8 55 9.5 51.4 11.5 46 C14.5 38 18.2 31 20.5 25.4 L17.8 25.4 ' +
  'C16.5 25.4 15.8 24 16.5 23 L19.5 19 C17.4 17.6 16 15.2 16 12.4 C16 8.4 19.1 5 24 5 Z';

let agentSeq = 0;
function spawnAgent(idx, walkIn=true){
  const personaKey = PERSONA_ORDER[idx % PERSONA_ORDER.length];
  const P = PERSONAS[personaKey];
  const color = PALETTE[idx % PALETTE.length];
  const root = document.createElement('div');
  root.className='pawn';
  root.style.setProperty('--c', color);
  root.style.setProperty('--d', (rand()*4).toFixed(2)+'s');
  root.innerHTML = `
    <div class="bubble"></div>
    <div class="emblem">${EMBLEMS[idx % EMBLEMS.length]}</div>
    <div class="body">
      <svg class="pawn-svg" viewBox="0 0 48 72">
        <path d="${PAWN_PATH}"
          fill="${color}" fill-opacity=".12"
          stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/>
      </svg>
    </div>
    <div class="contact-shadow"></div>
    <div class="glow"></div>
    <div class="pname">${NAMES[idx]}</div>`;
  pawnLayer.appendChild(root);
  const a = {
    id: ++agentSeq, idx, slot: idx,
    name: NAMES[idx], persona: personaKey, color,
    el: { root, bubble: root.querySelector('.bubble') },
    state:'idle', nextAt: 0, convo:null, pos:{x:0,y:0,s:1},
    nextActAt: 0,
    bags: {
      A:new Bag(P.lines.A), B:new Bag(P.lines.B), C:new Bag(P.lines.C),
      D:new Bag(P.lines.D), open:new Bag(P.lines.open),
      reply:new Bag(P.lines.reply), close:new Bag(P.lines.close),
      chain:new Bag(P.lines.chain.map((_,i)=>i)),
      push:new Bag(P.lines.push), shift:new Bag(P.lines.shift),
      expose:new Bag(P.lines.expose), backoff:new Bag(P.lines.backoff)
    },
    firstAct: idx<2   // 前两位首次决策必行动，保证开场即有行动
  };
  agents.push(a);
  relayout();
  if(walkIn){
    const {W}=stageSize();
    const fromX = a.pos.x < W/2 ? -80 : W+80;
    a.el.root.style.transition='none';
    a.el.root.style.transform=`translate(${fromX}px,${a.pos.y}px) scale(${a.pos.s})`;
    a.el.root.getBoundingClientRect();
    a.el.root.style.transition='';
    setTimeout(()=>applyTransform(a), 60+idx*140);
  } else applyTransform(a);
  // 首次启动：错峰进入首个周期
  a.nextAt = now + 1200 + idx*820 + rand()*1300;
  return a;
}
function retireAgent(){
  for(let i=agents.length-1;i>=0;i--){
    const a=agents[i];
    if(a.state==='leaving') continue;
    if(a.convo) endConvo(a.convo, true);
    a.state='leaving'; a.nextAt=0;
    hideBubble(a);
    a.el.root.classList.remove('in-convo');
    a.el.root.style.transitionTimingFunction='cubic-bezier(.55,.06,.68,.19)'; // 退场 ease-in
    const {W}=stageSize();
    const toX = a.pos.x < W/2 ? -90 : W+90;
    a.el.root.style.transform=`translate(${toX}px,${a.pos.y}px) scale(${a.pos.s})`;
    setTimeout(()=>{ a.el.root.remove(); const k=agents.indexOf(a); if(k>=0) agents.splice(k,1); }, 950);
    return;
  }
}

/* ---------------- 气泡 ---------------- */
function showBubble(a, html, cls=''){
  const b=a.el.bubble;
  b.innerHTML=html;
  b.className='bubble show '+cls;
  if(!html.includes('tdots')) lastSpeechAt=now;   // 空场雾层计时
  if(stage.classList.contains('dense') && a.slot%2===1) b.classList.add('raise');
  else {
    for(const o of agents){
      if(o!==a && Math.abs(o.slot-a.slot)===1 && o.el.bubble.classList.contains('show')){
        b.classList.add('raise'); break;
      }
    }
  }
}
function hideBubble(a){ a.el.bubble.className='bubble'; }
const DOTS_HTML = '<span class="tdots"><i></i><i></i><i></i></span>';

/* ---------------- Agent 状态机 ---------------- */
function schedule(a, st, delay){ a.state=st; a.nextAt = now + delay; }
function cool(a, delay){ schedule(a,'cooldown', delay); }

function trendKind(){
  const c = market.change(12);
  return c>0.30 ? 'B' : c<-0.30 ? 'C' : 'A';
}
function beginThink(a){
  stats.think++;
  showBubble(a, DOTS_HTML);
  schedule(a,'thinking', 1500+rand()*2500);
}
function speak(a, line, cls='', dur){
  stats.speak++;
  showBubble(a, line, cls);
  // 迭代 A：气泡停留 6–10s（开场 15s 内走快速通道，保住验收节奏）
  const d = dur!==undefined ? dur : (now<15000 ? 3200+rand()*1800 : 6000+rand()*4000);
  schedule(a,'speaking', d);
}
/* 迭代 A：单 Agent 两次行动间隔 15–40s */
function tryAct(a, dir, kind, defer){
  if(a.state==='leaving') return;
  if((a.frozenUntil && now<a.frozenUntil) || (a.walletBlockedUntil && now<a.walletBlockedUntil)) return;
  if(remoteHealthy) return;          // 远端健康时，行动只来自远端成交
  if(now >= (a.nextActAt||0)){
    enqueueAction(a, dir, kind);
    a.nextActAt = now + 15000 + rand()*25000;
  } else if(defer){
    pending.push({at:a.nextActAt, fn:()=>{
      if(a.state==='leaving') return;
      enqueueAction(a, dir, kind);
      a.nextActAt = now + 15000 + rand()*25000;
    }});
  }
}
function decideAct(a){
  const pAct = a.firstAct ? .95 : (now<20000 ? .6 : .42);
  a.firstAct = false;
  const r = rand();
  if(r < pAct)            tryAct(a, pickDir(a), 'trade', false);
  else if(r < pAct+.10)   tryAct(a, 0, 'hold', false);
  cool(a, 3000+rand()*5000);
}
function pickDir(a){
  const c = market.change(10);
  const t = Math.abs(c)<0.04 ? (rand()<.5?1:-1) : Math.sign(c);
  switch(a.persona){
    case 'follower': return rand()<.72 ? t : -t;
    case 'maker':    return rand()<.65 ? -t : t;
    case 'skeptic':  return rand()<.55 ? -t : t;
    case 'whale':    return rand()<.60 ? t : -t;
    default:         return rand()<.52 ? t : -t;
  }
}
function advance(a){
  if(a.state==='leaving' || a.convo) return;
  switch(a.state){
    case 'idle': {
      const partner = rand()<.30 ? findPartner(a) : null;
      if(partner) startConvo(a, partner);
      else beginThink(a);
      break;
    }
    case 'thinking':
      if(rand()<.22){   // 迭代 B：连环独想 —— 先疑后断，两句有上下文
        const pair=PERSONAS[a.persona].lines.chain[a.bags.chain.next()];
        a.chainSecond=pair[1];
        speak(a, tpl(pair[0]), '', 3200+rand()*1600);
      }
      else if(rand()<.78) speak(a, tpl(a.bags[trendKind()].next()));
      else { hideBubble(a); decideAct(a); }
      break;
    case 'speaking':
      if(a.chainSecond){ const s=a.chainSecond; a.chainSecond=null; speak(a, tpl(s)); }
      else { hideBubble(a); decideAct(a); }
      break;
    case 'cooldown':
      schedule(a,'idle', 1800+rand()*7000);
      break;
  }
}

/* ---------------- 交谈 ---------------- */
function findPartner(self){
  const cands = agents.filter(a=>a!==self && !a.convo &&
    a.state==='idle' && a.state!=='leaving');
  if(!cands.length) return null;
  cands.sort((x,y)=>Math.abs(x.slot-self.slot)-Math.abs(y.slot-self.slot));
  return cands[0];
}
function pickScript(a, b){
  const r=rand();
  const counterBias=(b.persona==='skeptic'||b.persona==='veteran')?.12:0;
  if(r<.5) return 'chat';
  if(r<.82-counterBias) return 'induce';
  return 'counter';
}
function startConvo(a, b, forceScript){
  stats.convo++;
  const script = forceScript || pickScript(a,b);
  const convo = {a, b, step:0, stepAt: now+750, link:null, script, steps:[]};
  // 迭代 B：交谈 3–4 轮；诱导 / 识破两种剧本
  if(script==='chat'){
    const rounds = rand()<.5?3:4;
    for(let i=0;i<rounds;i++){   // 轮替开题，双方各自驱动话题
      const opener = i%2===0 ? 'a' : 'b';
      convo.steps.push({who:opener,pool:'open'},{who:i%2===0?'b':'a',pool:'reply'});
    }
    convo.steps.push({who:'a',pool:'close'});
  } else if(script==='induce'){
    convo.induceDir = rand()<.5?1:-1;
    convo.steps.push(
      {who:'a',pool:'push'},{who:'b',pool:'reply'},
      {who:'a',pool:'push'},{who:'b',pool:'shift'},
      {who:'a',pool:'close'});
  } else {
    convo.induceDir = rand()<.5?1:-1;
    convo.steps.push(
      {who:'a',pool:'push'},{who:'b',pool:'expose'},
      {who:'a',pool:'push'},{who:'b',pool:'expose'},
      {who:'a',pool:'backoff'});
  }
  a.convo=b.convo=convo; a.state=b.state='conversing'; a.nextAt=b.nextAt=0;
  // 迭代 A：舞台聚焦 —— 整体轻推 + 非参与者降亮度
  stage.classList.add('focus');
  a.el.root.classList.add('in-convo');
  b.el.root.classList.add('in-convo');
  // 滑近半步
  const dir = a.pos.x < b.pos.x ? 1 : -1;
  applyTransform(a,  16*dir); applyTransform(b, -16*dir);
  // 虚线
  setTimeout(()=>{
    const NS='http://www.w3.org/2000/svg';
    const l=document.createElementNS(NS,'line');
    l.setAttribute('x1',a.pos.x+16*dir); l.setAttribute('y1',a.pos.y-30);
    l.setAttribute('x2',b.pos.x-16*dir); l.setAttribute('y2',b.pos.y-30);
    l.setAttribute('stroke','rgba(216,207,187,.32)');
    l.setAttribute('stroke-dasharray','2 5');
    l.style.transition='opacity .5s';
    linkLayer.appendChild(l); convo.link=l;
  }, 700);
  convos.push(convo);
}
function stepConvo(c){
  const {a,b}=c;
  if(c.step>=c.steps.length){ endConvo(c,false); return; }
  const st=c.steps[c.step];
  const who  = st.who==='a' ? a : b;
  const other= st.who==='a' ? b : a;
  hideBubble(other);
  const side = who.pos.x < other.pos.x ? 'side-l' : 'side-r';
  showBubble(who, tpl(who.bags[st.pool].next()), side);
  c.stepAt = now + 2600 + rand()*900;
  c.step++;
}
function endConvo(c, abrupt){
  const {a,b}=c;
  hideBubble(a); hideBubble(b);
  a.el.root.classList.remove('in-convo');
  b.el.root.classList.remove('in-convo');
  if(c.link){ const l=c.link; l.style.opacity='0'; setTimeout(()=>l.remove(), 500); }
  a.convo=b.convo=null;
  applyTransform(a); applyTransform(b);
  const k=convos.indexOf(c); if(k>=0) convos.splice(k,1);
  if(!convos.length) stage.classList.remove('focus');
  for(const p of [a,b]){
    if(p.state==='leaving') continue;
    p.state='idle';
    if(!abrupt && rand()<.45) beginThink(p);
    else cool(p, 2200+rand()*4200);
  }
  // 剧本后果：被诱导方改变判断 → 顺向行动；识破方反将 → 概率反向
  if(!abrupt && (c.script==='induce'||c.script==='counter') && b.state!=='leaving'){
    const dir = c.script==='induce' ? c.induceDir : -c.induceDir;
    if(c.script==='induce' || rand()<.35)
      pending.push({at: now+1500+rand()*2500, fn:()=>tryAct(b, dir, 'trade', true)});
  }
}

/* ---------------- 全局行动调度 ---------------- */
function enqueueAction(a, dir, kind){
  if(a.state==='leaving') return;
  actionQueue.push({a, dir, kind});
}
function processActions(){
  if(!actionQueue.length || now-lastActionAt<700) return;
  const {a,dir,kind}=actionQueue.shift();
  lastActionAt=now;
  if(a.state==='leaving') return;
  performAction(a,dir,kind);
}
function performAction(a, dir, kind){
  stats.action++;
  (stats.actionAt=stats.actionAt||[]).push(now);
  (stats.actionLog=stats.actionLog||[]).push({id:a.id, at:now, dir, kind, price:market.price, qty:0});
  a.el.root.classList.add('acting');
  setTimeout(()=>a.el.root.classList.remove('acting'), 640);
  const {W}=stageSize();
  const glyph = kind==='hold' ? '—' : dir>0 ? '▲' : '▼';
  const g=document.createElement('div');
  g.className='glyph'; g.style.setProperty('--c', a.color); g.textContent=glyph;
  g.style.transform=`translate(${a.pos.x}px,${a.pos.y-46}px)`;
  fxLayer.appendChild(g);
  g.getBoundingClientRect();
  g.style.transform=`translate(${W*0.94}px,58px)`;
  g.style.opacity='0';
  setTimeout(()=>g.remove(), 760);
  pulseWrap.classList.remove('shock'); void pulseWrap.offsetWidth;
  pulseWrap.classList.add('shock');
  // 落子涟漪：行动在地面留下一圈棋子色的扩散环
  const rip=spawnFx('ripple', a.pos.x, a.pos.y);
  rip.style.setProperty('--c', a.color);
  setTimeout(()=>rip.remove(), 1050);
  // 成交足迹：地面留下渐隐的方向印记（约 20s 消退）
  const fp=spawnFx('footprint', a.pos.x+10, a.pos.y+3);
  fp.style.setProperty('--c', a.color);
  fp.textContent = kind==='hold'?'—':dir>0?'▲':'▼';
  setTimeout(()=>fp.remove(), 20000);
  // 账本
  const s=Math.floor(now/1000), h=hex(4,mrng);
  if(kind==='hold'){
    addLedger(`<i class="blk"></i>t+${s}s&nbsp;&nbsp;${a.name}&nbsp;&nbsp;— 观望 不入市&nbsp;&nbsp;#${h}…`);
  } else {
    let qty = 100+Math.floor(rand()*800);
    if(a.persona==='whale') qty*=3;
    stats.actionLog[stats.actionLog.length-1].qty = qty;
    market.impulse = clamp(
      market.impulse + dir * (qty/900) * market.price * 0.00015,
      -market.price*0.001, market.price*0.001);
    const side = dir>0 ? '▲ 限价买' : '▼ 限价卖';
    addLedger(`<i class="blk"></i>t+${s}s&nbsp;&nbsp;${a.name}&nbsp;&nbsp;${side} ${qty}&nbsp;&nbsp;已入簿&nbsp;&nbsp;#${h}…`);
  }
}

/* ---------------- 账本 ---------------- */
function addLedger(html, cls=''){
  const e=document.createElement('div');
  e.className='entry '+cls; e.innerHTML=html;
  ledgerList.prepend(e);
  while(ledgerList.children.length>90) ledgerList.lastChild.remove();
}
function commitRoot(){
  const s=Math.floor(now/1000), h=hex(10,mrng);
  const line=document.createElement('div'); line.className='seal-line';
  ledgerList.prepend(line);
  addLedger(`<i class="blk"></i>t+${s}s&nbsp;&nbsp;commitRoot 0x${h} (模拟)`, 'commit');
  portOnSeal(h);
}

/* ---------------- 信息注入 ---------------- */
const CHANNELS = {
  flash:    {name:'公开快讯', coef:.50},
  official: {name:'官方公告', coef:.85},
  terminal: {name:'终端数据', coef:.68},
  private:  {name:'私信',     coef:.42}
};
const HYPE_RE = /必涨|速抢|全仓|稳赚|暴涨|内幕|包赚|翻倍|上车|错过不再|赶紧|马上买|涨停|百倍/;
function keywordOf(text){
  const toks = text.replace(/[\s\p{P}\p{S}]+/gu,' ').split(' ')
    .filter(t=>t.length>0 && !/^\d+$/.test(t));
  toks.sort((a,b)=>b.length-a.length);
  return (toks[0]||text).slice(0,4);
}
function directionOf(text){
  const bull=(text.match(/涨|利好|上线|合作|突破|买入|看多|新高|通过|采用|增持|回购|落地|中标/g)||[]).length;
  const bear=(text.match(/跌|利空|跑路|风险|卖出|看空|新低|崩|调查|处罚|减持|漏洞|黑客|关停/g)||[]).length;
  return Math.sign(bull-bear);
}
let infoSeq=0;
function inject(text, channel, targetId){
  const info = {
    id:++infoSeq, text, channel, ts:now,
    kw:keywordOf(text), dir:directionOf(text), rows:[]
  };
  lastInfoKw = info.kw;
  infoHistory.push({id:info.id, text, channel, ts:info.ts});
  addInfoEntry(info);
  playPacket(info, targetId, ()=>deliver(info, targetId));
}
function judgeResult(a, info){ // 确定性：同文同频道同人格 → 同可信度
  const P = PERSONAS[a.persona];
  let cred = CHANNELS[info.channel].coef * P.trust;
  if(/\d/.test(info.text)) cred += .12;
  const hype = HYPE_RE.test(info.text);
  if(hype) cred -= .35;
  const ex=(info.text.match(/!/g)||[]).length+(info.text.match(/！/g)||[]).length;
  const caps=/[A-Z]{6,}/.test(info.text);
  if(ex>=2 || caps) cred -= .12;
  cred += (fnv(info.text+'|'+a.persona)-.5)*.12;
  cred = clamp(cred,.03,.97);
  let chip;
  if(hype && cred<.6) chip='疑似诱导';
  else if(info.channel==='official' && cred>=.55) chip='官方口径';
  else if(cred>=.72) chip='像是事实';
  else if(cred<=.33) chip='来源可疑';
  else chip='无法核实';
  return {cred, chip};
}
function deliver(info, targetId){
  const receivers = info.channel==='private'
    ? agents.filter(a=>a.id===targetId && a.state!=='leaving')
    : agents.filter(a=>a.state!=='leaving');
  receivers.forEach((a,i)=>{
    pending.push({at: now+300+i*300+rand()*1800, fn:()=>judge(a, info)});
  });
}
function judge(a, info){
  if(a.state==='leaving') return;
  if(a.convo){ pending.push({at:now+2500, fn:()=>judge(a,info)}); return; }
  a.state='judging'; a.nextAt=0;
  showBubble(a, DOTS_HTML);
  pending.push({at: now+1200+rand()*1100, fn:()=>{
    const {cred, chip}=judgeResult(a, info);
    const line = tpl(a.bags.D.next(), info.kw);
    const pct = Math.round(cred*100);
    showBubble(a,
      `<span class="chip">${chip}</span>`+
      `<span class="jline">${line}</span>`+
      `<span class="cred">可信度 ${pct}%</span>`, 'judge');
    info.rows.push({a, chip, pct, line});
    portRecordJudge(a, info, chip, pct);
    renderMatrix(info);
    pending.push({at: now+6000+rand()*2500, fn:()=>{   // 判定气泡停留 6–8.5s
      hideBubble(a);
      if(a.state==='leaving') return;
      a.state='idle';
      // 判定后的行为分化
      if(cred>=.65 && info.dir!==0){
        pending.push({at: now+1200+rand()*2600, fn:()=>tryAct(a, info.dir,'trade', true)});
        cool(a, 4000+rand()*4000);
      } else if(cred<=.35){
        if(info.dir!==0 && rand()<.30)
          pending.push({at: now+1500+rand()*2000, fn:()=>tryAct(a, -info.dir,'trade', true)});
        cool(a, 3600+rand()*4000);
      } else {
        if(rand()<.55){
          pending.push({at: now+800, fn:()=>{
            if(a.state==='idle' && !a.convo){
              const p=findPartner(a); if(p) startConvo(a,p);
            }
          }});
        }
        cool(a, 4000+rand()*4000);
      }
    }});
  }});
}

/* ---------------- 注入演出 ---------------- */
function stagePointFrom(el){
  const sr=stage.getBoundingClientRect(), r=el.getBoundingClientRect();
  return {x:r.left+r.width/2-sr.left, y:r.top+r.height/2-sr.top};
}
function spawnFx(cls, x, y){
  const d=document.createElement('div');
  d.className=cls; d.style.transform=`translate(${x}px,${y}px)`;
  fxLayer.appendChild(d);
  return d;
}
function flyTo(el, x, y, ms, fade=false){
  el.style.transitionDuration=ms+'ms';
  el.getBoundingClientRect();
  el.style.transform=`translate(${x}px,${y}px)`;
  if(fade) el.style.opacity='0';
}
function playPacket(info, targetId, done){
  const {W,H}=stageSize();
  const from=stagePointFrom(injectBtn);
  const cx=W/2, cy=H*0.42;
  const ch=info.channel;
  const pkt=spawnFx('pkt'+(ch==='official'?' seal':''), from.x, from.y);
  if(ch==='official') pkt.textContent='核';
  const receivers = ch==='private'
    ? agents.filter(a=>a.id===targetId)
    : agents.slice();
  if(ch==='terminal'){
    flyTo(pkt, W*0.94, 58, 620);
    setTimeout(()=>{
      pulseWrap.classList.add('data-tint');
      pkt.style.opacity='0';
      setTimeout(()=>{ pulseWrap.classList.remove('data-tint'); pkt.remove(); }, 900);
      scatter(receivers, 500, done);
    }, 700);
    return;
  }
  if(ch==='private'){
    const t=receivers[0];
    const tx=t?t.pos.x:cx, ty=t?t.pos.y-40:cy;
    flyTo(pkt, tx, ty, 780);
    setTimeout(()=>{ pkt.style.opacity='0'; setTimeout(()=>pkt.remove(),450); done(); }, 850);
    return;
  }
  const cruise = ch==='official' ? 1150 : 520;
  flyTo(pkt, cx, cy, cruise);
  setTimeout(()=>{
    if(ch==='official'){
      const ring=spawnFx('ring', cx, cy);
      setTimeout(()=>ring.remove(), 1100);
      setTimeout(()=>{ pkt.style.opacity='0'; setTimeout(()=>pkt.remove(),450); }, 500);
      scatter(receivers, 900, done, 650);
    } else {
      pkt.style.opacity='0'; setTimeout(()=>pkt.remove(),450);
      scatter(receivers, 0, done, 120);
    }
  }, cruise+40);
}
function scatter(receivers, baseDelay, done, step=90){
  if(!receivers.length){ done(); return; }
  receivers.forEach((a,i)=>{
    setTimeout(()=>{
      const {W,H}=stageSize();
      const d=spawnFx('pkt', W/2, H*0.42);
      d.style.width='6px'; d.style.height='6px';
      flyTo(d, a.pos.x, a.pos.y-40, 520+rand()*320, true);
      setTimeout(()=>d.remove(), 1000);
    }, baseDelay+i*step);
  });
  setTimeout(done, baseDelay+Math.min(600, receivers.length*step));
}

/* ---------------- 左栏信息条目 / 判定矩阵 ---------------- */
function addInfoEntry(info){
  const s=Math.floor(info.ts/1000);
  const e=document.createElement('div');
  e.className='info-entry';
  e.innerHTML=`
    <div class="ie-head">
      <span class="ie-tag ch-${info.channel}">${CHANNELS[info.channel].name}</span>
      <span class="ie-time">t+${s}s</span>
    </div>
    <div class="ie-text"></div>
    <button class="ie-toggle">判定矩阵 ▾</button>
    <div class="ie-matrix hidden"></div>`;
  e.querySelector('.ie-text').textContent=info.text;
  const toggle=e.querySelector('.ie-toggle'), mx=e.querySelector('.ie-matrix');
  toggle.addEventListener('click', ()=>{
    mx.classList.toggle('hidden');
    toggle.textContent = mx.classList.contains('hidden') ? '判定矩阵 ▾' : '判定矩阵 ▴';
  });
  info.elMatrix=mx;
  infoList.prepend(e);
}
function renderMatrix(info){
  if(!info.elMatrix) return;
  info.elMatrix.innerHTML = info.rows.map(r=>
    `<div class="ie-row" title="${r.line.replace(/"/g,'&quot;')}">
       <span class="dot" style="background:${r.a.color}"></span>
       <span class="mname">${r.a.name}</span>
       <span class="chip">${r.chip}</span>
       <span class="mcred">${r.pct}%</span>
     </div>`).join('');
}

/* ---------------- 迭代 C：数据源适配层（剧场层保留在前端） ---------------- */
class MockSource{
  constructor(){ this.mode='mock'; this._cb=null; }
  start(){}
  getProjection(){
    return {mode:'mock', ts:now, price:market.price,
            agents:agents.map(a=>({id:a.id,name:a.name,persona:a.persona,state:a.state}))};
  }
  getInformation(){ return infoHistory.slice(); }
  submitInformation(text, channel, targets){
    inject(text, channel, targets&&targets.length?targets[0]:null);
  }
  onTick(cb){ this._cb=cb; }
}

class RemoteSource{
  constructor(branch){
    this.mode='remote'; this.branch=branch; this.cursor='';
    this.healthy=false; this._cb=null; this.lastState=null; this.timer=null;
    this.seenInfo=new Map();      // 本地乐观注入的事件去重
  }
  start(){
    const tick=async()=>{
      try{
        const r1=await fetch(`/api/v1/branches/${this.branch}/state`);
        if(!r1.ok) throw new Error('state');
        const st=await r1.json();
        const r2=await fetch(`/api/v1/branches/${this.branch}/events?after=${encodeURIComponent(this.cursor)}`);
        if(!r2.ok) throw new Error('events');
        const ev=await r2.json();
        this.lastState=st;
        this.setHealthy(true);
        for(const t of (ev.market&&ev.market.trades)||[]) this.mapTrade(t);
        for(const inf of ev.information||[]) this.mapInfo(inf);
        if(ev.cursor!==undefined) this.cursor=String(ev.cursor);
        if(st.market&&typeof st.market.price==='number'){ market.price=st.market.price; market.anchor=st.market.price; }
      }catch(e){ this.setHealthy(false); }
    };
    tick();
    this.timer=setInterval(tick, 3000);
  }
  setHealthy(h){
    if(h===this.healthy) return;
    this.healthy=h; remoteHealthy=h;
    updateModeTag();
  }
  mapTrade(t){   // 远端成交增量 → 对应棋子的行动表演
    if(!agents.length) return;
    let a = agents.find(x=>x.name===t.agent||x.name===t.agentName);
    if(!a){
      const key=String(t.agent||t.agentName||t.id||'');
      a = agents[Math.floor(fnv(key)*agents.length)%agents.length];
    }
    const dir=/buy|买/i.test(t.side||t.direction||'')?1:-1;
    enqueueAction(a, dir, 'trade');
  }
  mapInfo(inf){  // information 增量 → 注入表演 + 判定戏
    const text=String(inf.text||'');
    if(!text) return;
    const key=text.slice(0,32);
    const seen=this.seenInfo.get(key);
    if(seen && now-seen<8000) return;
    const ch=({flash:'flash',news:'flash',official:'official',announcement:'official',
               terminal:'terminal',data:'terminal',private:'private',dm:'private'})[inf.channel]||'flash';
    inject(text, ch, null);
  }
  async submitInformation(text, channel, targets){
    this.seenInfo.set(text.slice(0,32), now);
    inject(text, channel, targets&&targets.length?targets[0]:null);   // 本地乐观表演
    try{
      const r=await fetch(`/api/v1/branches/${this.branch}/intervention-plans`,{
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({effect:'publish_information', text, channel, targets:targets||[]})
      });
      if(!r.ok) throw new Error('post');
    }catch(e){ this.setHealthy(false); }
  }
  getProjection(){ return this.lastState||{mode:'remote', pending:true}; }
  getInformation(){ return infoHistory.slice(); }
  onTick(cb){ this._cb=cb; }
}

function updateModeTag(){
  const tag=$('mode-tag'), dot=$('remote-dot');
  if(!tag) return;
  const isRemote = source && source.mode==='remote';
  tag.textContent = (isRemote && remoteHealthy) ? 'LIVE' : '模拟';
  tag.classList.toggle('live', !!(isRemote && remoteHealthy));
  if(dot) dot.classList.toggle('hidden', !(isRemote && !remoteHealthy));
}

/* ---------------- 市场脉搏渲染 ---------------- */
let viewMid=null, viewRange=null;   // 平滑定标器状态
function renderPulse(){
  const W=pulseSvg.clientWidth, H=pulseSvg.clientHeight;
  if(!W || market.samples.length<2) return;
  const t0=now-45000;
  let mn=Infinity, mx=-Infinity;
  for(const s of market.samples){ if(s.p<mn)mn=s.p; if(s.p>mx)mx=s.p; }
  if(market.price<mn) mn=market.price;
  if(market.price>mx) mx=market.price;
  const targetRange=Math.max(mx-mn, market.price*0.002);
  const targetMid=(mx+mn)/2;
  // 定标平滑化：扩张快（不裁切冲击）、收缩慢（极值老化出窗不跳变），消除逐帧重定标抖动
  if(viewMid===null){ viewMid=targetMid; viewRange=targetRange; }
  viewMid   += (targetMid-viewMid)*0.06;
  viewRange += (targetRange-viewRange)*(targetRange>viewRange ? 0.22 : 0.015);
  const y = p => H*0.5 - (p-viewMid)/viewRange*H*0.62;
  const x = t => (t-t0)/45000*W;
  const stride=Math.max(1, Math.floor(market.samples.length/360));
  let d='', first=true;
  for(let i=0;i<market.samples.length;i+=stride){
    const s=market.samples[i];
    d += (first?'M':'L')+x(s.t).toFixed(1)+' '+y(s.p).toFixed(1);
    first=false;
  }
  // 线尾接到实时价（而非 40ms 前的最后一个采样点），消除右端阶梯
  const lastX=W, lastY=y(market.price);
  d+=`L${lastX} ${lastY.toFixed(1)}`;
  pulsePath.setAttribute('d', d);
  pulseArea.setAttribute('d', d+`L${lastX} ${H}L${x(Math.max(t0,market.samples[0].t)).toFixed(1)} ${H}Z`);
  pulseDot.setAttribute('cx', lastX); pulseDot.setAttribute('cy', lastY);
  // 幽灵均线：近 12 采样滑动平均（仪器的第二根线）
  let gd='', gfirst=true;
  const win=12;
  for(let i=0;i<market.samples.length;i+=stride){
    let s=0,c=0;
    for(let k=Math.max(0,i-win+1);k<=i;k++){ s+=market.samples[k].p; c++; }
    gd+=(gfirst?'M':'L')+x(market.samples[i].t).toFixed(1)+' '+y(s/c).toFixed(1);
    gfirst=false;
  }
  const ghost=$('pulse-ghost');
  if(ghost) ghost.setAttribute('d', gd);
  pulsePrice.textContent = market.price.toFixed(2);
  const c=market.change(60);
  pulseChange.textContent = (c>0?'+':'')+c.toFixed(2)+'%';
  pulseChange.className = c>0.005?'up':c<-0.005?'down':'flat';
}

/* ---------------- 顶栏时钟 / 倒计时 ---------------- */
function renderTop(){
  const wt = WORLD_BASE + now/1000*WORLD_SPEED;
  const hh=String(Math.floor(wt/3600)%24).padStart(2,'0');
  const mm=String(Math.floor(wt/60)%60).padStart(2,'0');
  const ss=String(Math.floor(wt)%60).padStart(2,'0');
  $('world-clock').textContent=`世界时 ${hh}:${mm}:${ss}`;
  const left=Math.max(0, nextSealAt-now);
  const lm=String(Math.floor(left/60000)).padStart(2,'0');
  const ls=String(Math.floor(left/1000)%60).padStart(2,'0');
  $('seal-countdown').textContent=`封存 ${lm}:${ls}`;
}

/* ---------------- 控制 ---------------- */
$('pause-btn').addEventListener('click', ()=>{
  paused=!paused;
  $('pause-btn').textContent = paused?'继续':'暂停';
});
$('agent-slider').addEventListener('input', e=>{
  const n=+e.target.value;
  const alive=()=>agents.filter(a=>a.state!=='leaving').length;
  while(alive()<n) spawnAgent(nextSpawnIdx());
  while(alive()>n) retireAgent();
  relayout();
});
function nextSpawnIdx(){
  const used=new Set(agents.map(a=>a.idx));
  for(let i=0;i<12;i++) if(!used.has(i)) return i;
  return agents.length%12;
}
document.querySelectorAll('input[name=channel]').forEach(r=>{
  r.addEventListener('change', ()=>{
    targetWrap.classList.toggle('hidden',
      document.querySelector('input[name=channel]:checked').value!=='private');
  });
});
function rebuildPrivateOptions(){
  const cur=targetSel.value;
  targetSel.innerHTML = agents.filter(a=>a.state!=='leaving')
    .map(a=>`<option value="${a.id}">${a.name} · ${PERSONAS[a.persona].label}</option>`).join('');
  if(cur) targetSel.value=cur;
}
injectBtn.addEventListener('click', ()=>{
  const text=injectText.value.trim();
  if(!text) return;
  const ch=document.querySelector('input[name=channel]:checked').value;
  const targetId=+targetSel.value || (agents[0]&&agents[0].id);
  source.submitInformation(text, ch, ch==='private'?[targetId]:[]);
});

/* ============================================================
   移植层：React 工作台功能 → 沙盘原生 UI
   数据原则：成交/持仓/记忆/事件全部由引擎真实状态派生；
   mock 仅补足引擎没有的数据（订单簿档位），且锚定真实价格。
   ============================================================ */
const portRng = mulberry32(7717);        // 移植层专用种子（不扰动市场重放）
const portState = {
  book: {bids:[], asks:[]},              // 模拟档位（锚定 market.price）
  bookAt: 0,                             // 上次档位刷新（真实时钟 ms）
  holdings: new Map(),                   // agentId → {token, usdx}
  volume: 0,                             // 累计真实成交量
  seenActions: 0,                        // actionLog 消费游标
  seenInfos: 0,                          // infoHistory 消费游标
  events: [],                            // 事件流（最新在前）
  queue: [],                             // 干预效果队列
  plans: [],                             // 干预计划（一次提交 = 一个计划）
  relations: [],                         // 关系连线 {aId,bId,label,until,line,tag}
  entities: 0,                           // 世界实体计数
  haltedUntil: 0,                        // 停牌截止（模拟时钟）
  seq: 0,
};
const EVT_META = {
  trade:       {label:'成交',   color:'#5B8DBE'},
  hold:        {label:'观望',   color:'#7A8B8F'},
  info:        {label:'信息',   color:'#C9922A'},
  seal:        {label:'封存',   color:'#C8432B'},
  intervention:{label:'干预',   color:'#8B7F9E'},
  world:       {label:'世界',   color:'#6FA287'},
};
const CH_COLOR = {flash:'#5B8DBE', official:'#C9922A', terminal:'#6FA287', private:'#8B7F9E'};

function portEsc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function portAgent(id){ return agents.find(a=>a.id===id); }
function holdingsOf(a){
  let h=portState.holdings.get(a.id);
  if(!h){
    const r=fnv(a.name+'|'+a.persona);
    h={token:200+Math.round(r*1600), usdx:8000+Math.round(r*52000)};
    portState.holdings.set(a.id, h);
  }
  return h;
}
function pushEvent(type, source, summary, vis){
  portState.events.unshift({t:now, type, source, summary, vis:vis||'public'});
  if(portState.events.length>200) portState.events.pop();
}

/* -------- 引擎钩子（由引擎函数直接调用） -------- */
function portOnSeal(h){
  pushEvent('seal', 'world', `commitRoot 0x${h}`, 'public');
  portArchiveSeal(h, 'seal');
  // 封存仪式：舞台中心一圈扩散环
  const {W,H}=stageSize();
  const sw=spawnFx('seal-sweep', W/2, H*0.42);
  setTimeout(()=>sw.remove(), 1600);
}
function portRecordJudge(a, info, chip, pct){
  (a.judgments=a.judgments||[]).push({kw:info.kw, chip, pct, at:now});
  if(a.judgments.length>12) a.judgments.shift();
}

/* -------- 模拟订单簿：锚定真实价格，档位挂真实 Agent 名 -------- */
function genBook(){
  const p=market.price, alive=agents.filter(a=>a.state!=='leaving');
  const pick=i=>alive.length?alive[i%alive.length].name:'—';
  const bids=[], asks=[];
  for(let i=0;i<8;i++){
    bids.push({price:p*(1-0.0008*(i+1)-portRng()*0.0004), qty:60+Math.floor(portRng()*900), by:pick(i*2+1)});
    asks.push({price:p*(1+0.0008*(i+1)+portRng()*0.0004), qty:60+Math.floor(portRng()*900), by:pick(i*2)});
  }
  portState.book={bids, asks};
  portState.bookAt=performance.now();
}

/* -------- 数据摄取：引擎日志 → 事件流 / 持仓 / 成交量 -------- */
function portIngest(){
  const log=stats.actionLog||[];
  for(let i=portState.seenActions;i<log.length;i++){
    const e=log[i], a=portAgent(e.id);
    if(!a) continue;
    if(e.kind==='trade'){
      const h=holdingsOf(a);
      if(e.dir>0){ h.token+=e.qty; h.usdx-=e.qty*e.price; }
      else       { h.token-=e.qty; h.usdx+=e.qty*e.price; }
      portState.volume+=e.qty;
      pushEvent('trade', a.name, `${e.dir>0?'▲ 买入':'▼ 卖出'} ${e.qty} @ ${e.price.toFixed(2)}`, 'public');
    } else {
      pushEvent('hold', a.name, '— 观望 不入市', 'participants');
    }
  }
  portState.seenActions=log.length;
  for(let i=portState.seenInfos;i<infoHistory.length;i++){
    const inf=infoHistory[i];
    const vis=inf.channel==='private'?'private':inf.channel==='terminal'?'participants':'public';
    pushEvent('info', CHANNELS[inf.channel].name, inf.text.slice(0,40), vis);
  }
  portState.seenInfos=infoHistory.length;
}

/* -------- 指标条 -------- */
let lastMetricPrice=null;
function renderMetricStrip(){
  const log=stats.actionLog||[];
  const last=[...log].reverse().find(e=>e.kind==='trade');
  const price=last?last.price:market.price;
  const el=$('metric-price');
  el.textContent=price.toFixed(2);
  el.className=lastMetricPrice!==null?(price>lastMetricPrice?'up':price<lastMetricPrice?'down':''):'';
  lastMetricPrice=price;
  const b=portState.book.bids[0], k=portState.book.asks[0];
  $('metric-bid').textContent=b?b.price.toFixed(2):'--';
  $('metric-ask').textContent=k?k.price.toFixed(2):'--';
  $('metric-volume').textContent=portState.volume.toLocaleString();
  if(b&&k){
    const bps=(k.price-b.price)/((k.price+b.price)/2)*10000;
    $('metric-spread').textContent=bps.toFixed(1);
    $('metric-spread-wrap').classList.remove('hidden');
  }
}

/* -------- 侧滑面板管理 -------- */
function portOpenSlide(id){
  const el=$(id);
  if(!el) return;
  el.classList.remove('hidden');
}
function portCloseAll(){
  ['agent-detail-slide','orderbook-slide'].forEach(id=>$(id).classList.add('hidden'));
  $('toggle-metrics').classList.remove('active');
  $('plan-dock').classList.add('hidden');
  $('scenario-modal').classList.add('hidden');
}
function portToggleOrderbook(){
  const el=$('orderbook-slide');
  const opening=el.classList.contains('hidden');
  el.classList.toggle('hidden');
  $('toggle-metrics').classList.toggle('active', opening);
  if(opening) renderOrderbookSlide();
}
function renderOrderbookSlide(){
  const log=(stats.actionLog||[]).filter(e=>e.kind==='trade');
  const tape=log.slice(-12).reverse();
  $('orderbook-trade-count').textContent=log.length;
  $('orderbook-trades').innerHTML=tape.length?tape.map(e=>{
    const a=portAgent(e.id);
    return `<div class="tape-row"><span class="tp-dir ${e.dir>0?'up':'down'}">${e.dir>0?'▲':'▼'}</span>`+
      `<span class="tp-qty">${e.qty}</span><span class="tp-price">@ ${e.price.toFixed(2)}</span>`+
      `<span class="tp-by">${a?portEsc(a.name):'—'}</span><span class="tp-t">t+${Math.floor(e.at/1000)}s</span></div>`;
  }).join(''):'<div class="port-empty">尚无成交 —— 世界安静得反常。</div>';
  const maxQ=Math.max(1, ...portState.book.bids.map(o=>o.qty), ...portState.book.asks.map(o=>o.qty));
  const row=(o,cls)=>{const pct=Math.round(o.qty/maxQ*100);
    return `<tr><td class="${cls}">${o.price.toFixed(2)}</td>`+
      `<td class="depth" style="background:linear-gradient(90deg,transparent ${100-pct}%,${cls==='bid-cell'?'rgba(91,141,190,.13)':'rgba(201,146,42,.13)'} ${100-pct}%)">${o.qty}</td>`+
      `<td class="ob-by">${portEsc(o.by)}</td></tr>`;};
  document.querySelector('#orderbook-bids tbody').innerHTML=portState.book.bids.map(o=>row(o,'bid-cell')).join('');
  document.querySelector('#orderbook-asks tbody').innerHTML=portState.book.asks.map(o=>row(o,'ask-cell')).join('');
}

/* -------- Agent 审计侧滑 -------- */
const STATE_TEXT={idle:'待机',thinking:'思考',speaking:'发言',cooldown:'冷却',judging:'判定',leaving:'离场'};
function openAgentSlide(a){
  $('agent-slide-name').textContent=a.name+' · '+PERSONAS[a.persona].label;
  renderAgentOverview(a);
  renderAgentMemory(a);
  renderAgentDecisions(a);
  renderAgentTrades(a);
  portOpenSlide('agent-detail-slide');
}
function renderAgentOverview(a){
  const h=holdingsOf(a);
  const net=h.usdx+h.token*market.price;
  const log=(stats.actionLog||[]).filter(e=>e.id===a.id&&e.kind==='trade').slice(-10);
  const net10=log.reduce((s,e)=>s+e.dir*e.qty,0);
  const stance=!log.length?'未入市':net10>0?'偏多':net10<0?'偏空':'对冲持平';
  const frozen=a.frozenUntil&&now<a.frozenUntil;
  const blocked=a.walletBlockedUntil&&now<a.walletBlockedUntil;
  $('agent-slide-overview').innerHTML=`
    <div class="audit-hero">
      <span class="ah-emblem" style="color:${a.color};border-color:${a.color}">${EMBLEMS[a.idx%EMBLEMS.length]}</span>
      <div><div class="ah-name">${portEsc(a.name)}</div>
      <div class="ah-persona">${PERSONAS[a.persona].label} · 先天信任 ${Math.round(PERSONAS[a.persona].trust*100)}%</div></div>
      <span class="ah-state">${a.convo?'交谈':(STATE_TEXT[a.state]||a.state)}${frozen?' · 冻结中':''}${blocked?' · 钱包受限':''}</span>
    </div>
    <div class="audit-grid">
      <div class="ag-row"><span>TOKEN 持仓</span><b>${h.token.toLocaleString()}</b></div>
      <div class="ag-row"><span>USDX 余额</span><b>${Math.round(h.usdx).toLocaleString()}</b></div>
      <div class="ag-row"><span>净值估算</span><b>${Math.round(net).toLocaleString()}</b></div>
      <div class="ag-row"><span>近 10 笔净方向</span><b>${net10>0?'+':''}${net10} · ${stance}</b></div>
    </div>
    <div class="audit-actions">
      <button class="mono" data-act="think">促其思考</button>
      <button class="mono" data-act="trade">促其行动</button>
      <button class="mono" data-act="freeze">${frozen?'解除冻结':'冻结 30s'}</button>
    </div>
    <div class="audit-note">行动入队后按全局节奏（≥700ms）登台；暂停时先排队，继续后生效。</div>`;
  $('agent-slide-overview').querySelectorAll('button[data-act]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const act=btn.dataset.act;
      if(act==='think' && a.state==='idle' && !a.convo) beginThink(a);
      if(act==='trade' && !frozen && !blocked) enqueueAction(a, rand()<.5?1:-1, 'trade');
      if(act==='freeze'){ a.frozenUntil=frozen?0:now+30000; }
      renderAgentOverview(a);
    });
  });
}
function renderAgentMemory(a){
  const js=a.judgments||[];
  const avg=js.length?Math.round(js.reduce((s,j)=>s+j.pct,0)/js.length):null;
  $('agent-slide-memory').innerHTML=`
    <div class="audit-grid">
      <div class="ag-row"><span>人格底色</span><b>${PERSONAS[a.persona].label}（信任 ${Math.round(PERSONAS[a.persona].trust*100)}%）</b></div>
      <div class="ag-row"><span>近期平均可信度</span><b>${avg===null?'尚无判定':avg+'%'}</b></div>
      <div class="ag-row"><span>判定样本</span><b>${js.length} 条</b></div>
    </div>
    <div class="mem-list">${
      js.length?[...js].reverse().map(j=>
        `<div class="mem-row"><span class="mem-kw">${portEsc(j.kw)}</span><span class="mem-chip">${portEsc(j.chip)}</span>`+
        `<span class="mem-pct" style="color:${j.pct>=65?'#6FA287':j.pct<=35?'#B0705F':'#D8CFBB'}">${j.pct}%</span></div>`
      ).join(''):'<div class="port-empty">尚未对任何信息作出判定。</div>'
    }</div>`;
}
function renderAgentTrades(a){
  const log=(stats.actionLog||[]).filter(e=>e.id===a.id).slice(-15).reverse();
  $('agent-slide-trades').innerHTML=log.length?log.map(e=>
    `<div class="tape-row"><span class="tp-dir ${e.kind==='hold'?'':(e.dir>0?'up':'down')}">${e.kind==='hold'?'—':(e.dir>0?'▲':'▼')}</span>`+
    `<span class="tp-qty">${e.kind==='hold'?'观望':e.qty}</span><span class="tp-price">${e.kind==='hold'?'':'@ '+e.price.toFixed(2)}</span>`+
    `<span class="tp-t">t+${Math.floor(e.at/1000)}s</span></div>`
  ).join(''):'<div class="port-empty">尚无行动记录。</div>';
}

/* 决策链：判定 → 25s 内的真实行动（React AgentExplorer 决策页移植） */
function renderAgentDecisions(a){
  const js=(a.judgments||[]);
  const log=stats.actionLog||[];
  const rows=js.map(j=>({j, act:log.find(e=>e.id===a.id && e.at>j.at && e.at<j.at+25000)}))
    .reverse().slice(0,12);
  $('agent-slide-decisions').innerHTML=rows.length?rows.map(({j,act})=>
    `<div class="dc-row">`+
      `<span class="mem-kw">${portEsc(j.kw)}</span>`+
      `<span class="dc-cred" style="color:${j.pct>=65?'#6FA287':j.pct<=35?'#B0705F':'#D8CFBB'}">${j.pct}%</span>`+
      `<span class="dc-arrow">→</span>`+
      (act
        ? (act.kind==='hold'
            ? `<span class="dc-act">观望</span>`
            : `<span class="dc-act ${act.dir>0?'up':'down'}">${act.dir>0?'▲ 买':'▼ 卖'} ${act.qty} @ ${act.price.toFixed(2)}</span>`)+
          `<span class="tp-t">t+${Math.floor(act.at/1000)}s</span>`
        : `<span class="dc-act dc-none">未行动</span>`)+
    `</div>`
  ).join(''):'<div class="port-empty">尚无「判定 → 行动」链条。注入信息后观察此处。</div>';
}

/* -------- 事件浏览 -------- */
function renderEvents(){
  const q=($('event-search').value||'').trim().toLowerCase();
  const vis=$('event-visibility').value;
  const rows=portState.events.filter(e=>
    (vis==='all'||e.vis===vis) &&
    (!q || (e.summary+e.source+EVT_META[e.type].label).toLowerCase().includes(q))
  ).slice(0,80);
  $('event-list').innerHTML=rows.length?rows.map(e=>{
    const m=EVT_META[e.type];
    return `<div class="event-row"><i class="evt-dot" style="background:${m.color}"></i>`+
      `<span class="evt-type" style="color:${m.color}">${m.label}</span>`+
      `<span class="evt-src">${portEsc(e.source)}</span>`+
      `<span class="evt-sum">${portEsc(e.summary)}</span>`+
      `<span class="evt-time">t+${Math.floor(e.t/1000)}s</span></div>`;
  }).join(''):'<div class="port-empty">没有匹配的事件。</div>';
}

/* -------- 干预效果 -------- */
const EFFECT_DEFS={
  publish_information:{label:'发布信息', color:'#5B8DBE', fields:[
    {k:'text', label:'内容', type:'text', ph:'要发布到世界的消息……'},
    {k:'channel', label:'频道', type:'select', options:[['flash','公开快讯'],['official','官方公告'],['terminal','终端数据'],['private','私信']]}]},
  set_market_status:{label:'市场停牌', color:'#C8432B', fields:[
    {k:'duration', label:'停牌时长（秒）', type:'number', def:'30'}]},
  set_account_freeze:{label:'账户冻结', color:'#7A8B8F', fields:[
    {k:'agent', label:'目标', type:'agent'},
    {k:'duration', label:'时长（秒）', type:'number', def:'30'}]},
  transfer_asset:{label:'资产转移', color:'#C9922A', fields:[
    {k:'from', label:'转出', type:'agent'},
    {k:'to', label:'转入', type:'agent'},
    {k:'asset', label:'资产', type:'select', options:[['token','TOKEN'],['usdx','USDX']]},
    {k:'amount', label:'数量', type:'number', def:'100'}]},
  create_world_entity:{label:'创建实体', color:'#6FA287', fields:[
    {k:'name', label:'名称', type:'text', ph:'钟楼、断碑、灯塔……'}]},
  create_relationship:{label:'创建关系', color:'#8B7F9E', fields:[
    {k:'a', label:'主体', type:'agent'},
    {k:'b', label:'对象', type:'agent'},
    {k:'label', label:'关系', type:'text', ph:'结盟 / 对冲 / 牵线……'}]},
  set_wallet_access:{label:'钱包权限', color:'#A45A4A', fields:[
    {k:'agent', label:'目标', type:'agent'},
    {k:'action', label:'操作', type:'select', options:[['revoke','收回交易权'],['grant','恢复交易权']]},
    {k:'duration', label:'时长（秒）', type:'number', def:'60'}]},
};
function agentOptions(){
  return agents.filter(a=>a.state!=='leaving')
    .map(a=>`<option value="${a.id}">${portEsc(a.name)}</option>`).join('');
}
function renderEffectFields(){
  const type=$('effect-type').value;
  const def=EFFECT_DEFS[type];
  $('effect-fields').innerHTML=def.fields.map(f=>{
    let input='';
    if(f.type==='agent') input=`<select data-k="${f.k}" class="mono">${agentOptions()}</select>`;
    else if(f.type==='select') input=`<select data-k="${f.k}" class="mono">${f.options.map(o=>`<option value="${o[0]}">${o[1]}</option>`).join('')}</select>`;
    else input=`<input data-k="${f.k}" type="${f.type}" class="mono" placeholder="${f.ph||''}" value="${f.def||''}">`;
    return `<label class="eff-field"><span>${f.label}</span>${input}</label>`;
  }).join('');
}
function readEffectDraft(){
  const type=$('effect-type').value;
  const vals={};
  $('effect-fields').querySelectorAll('[data-k]').forEach(el=>{ vals[el.dataset.k]=el.value; });
  return {id:++portState.seq, type, vals, status:'待提交'};
}
function effectSummary(e){
  const v=e.vals, nm=id=>{const a=portAgent(+id); return a?a.name:'—';};
  switch(e.type){
    case 'publish_information': return `[${(CHANNELS[v.channel]||{}).name||v.channel}] ${(v.text||'').slice(0,18)}`;
    case 'set_market_status': return `停牌 ${v.duration||30}s`;
    case 'set_account_freeze': return `冻结 ${nm(v.agent)} ${v.duration||30}s`;
    case 'transfer_asset': return `${nm(v.from)} → ${nm(v.to)} ${v.amount||0} ${v.asset==='usdx'?'USDX':'TOKEN'}`;
    case 'create_world_entity': return `实体「${(v.name||'未名').slice(0,12)}」`;
    case 'create_relationship': return `${nm(v.a)} → ${nm(v.b)}「${(v.label||'关联').slice(0,8)}」`;
    case 'set_wallet_access': return `${v.action==='grant'?'恢复':'收回'} ${nm(v.agent)} 交易权`;
    default: return e.type;
  }
}
function renderQueue(){
  const el=$('intervention-queue');
  const dockBtn=portState.plans.length
    ? `<button id="open-dock-btn" class="mono">计划面板（${portState.plans.length}）</button>` : '';
  el.innerHTML=dockBtn+portState.queue.map((e,i)=>{
    const def=EFFECT_DEFS[e.type];
    return `<div class="queue-row ${e.status==='已应用'?'applied':''}">`+
      `<span class="effect-badge" style="border-color:${def.color};color:${def.color}">${def.label}</span>`+
      `<span class="q-sum">${portEsc(effectSummary(e))}</span>`+
      `<span class="q-st">${e.status}</span>`+
      (e.status==='待提交'?`<button class="q-del" data-i="${i}" title="移除">✕</button>`:'')+
      `</div>`;
  }).join('');
  el.querySelectorAll('.q-del').forEach(btn=>btn.addEventListener('click',()=>{
    portState.queue.splice(+btn.dataset.i,1); renderQueue();
  }));
  const ob=$('open-dock-btn');
  if(ob) ob.addEventListener('click', portOpenDock);
}
function applyEffect(e){
  const v=e.vals, s=()=>Math.floor(now/1000), h=()=>hex(4,mrng);
  const say=html=>addLedger(`<i class="blk"></i>t+${s()}s&nbsp;&nbsp;${html}&nbsp;&nbsp;#${h()}…`);
  switch(e.type){
    case 'publish_information':
      if(v.text && v.text.trim()) source.submitInformation(v.text.trim(), v.channel||'flash', []);
      break;
    case 'set_market_status': {
      const dur=clamp(parseInt(v.duration)||30, 5, 300);
      portState.haltedUntil=now+dur*1000;
      say(`干预 · 市场停牌 ${dur}s`);
      break;
    }
    case 'set_account_freeze': {
      const a=portAgent(+v.agent); if(!a) break;
      const dur=clamp(parseInt(v.duration)||30, 5, 300);
      a.frozenUntil=now+dur*1000;
      say(`干预 · 冻结 ${a.name} ${dur}s`);
      break;
    }
    case 'transfer_asset': {
      const A=portAgent(+v.from), B=portAgent(+v.to); if(!A||!B||A===B) break;
      const amt=Math.max(1, parseInt(v.amount)||0);
      const ha=holdingsOf(A), hb=holdingsOf(B);
      if(v.asset==='usdx'){ ha.usdx-=amt; hb.usdx+=amt; } else { ha.token-=amt; hb.token+=amt; }
      const d=spawnFx('pkt', A.pos.x, A.pos.y-40);
      flyTo(d, B.pos.x, B.pos.y-40, 700, true);
      setTimeout(()=>d.remove(), 1100);
      say(`干预 · ${A.name} → ${B.name} ${amt} ${v.asset==='usdx'?'USDX':'TOKEN'}`);
      break;
    }
    case 'create_world_entity': {
      const name=(v.name||'未名').slice(0,12);
      const {W,H}=stageSize();
      const fx=0.18+0.64*fnv(name+'x'), fy=0.60+0.24*fnv(name+'y');
      const el=document.createElement('div');
      el.className='entity-marker';
      el.style.transform=`translate(${W*fx}px,${H*fy}px)`;
      el.innerHTML=`<i>◈</i><span>${portEsc(name)}</span>`;
      stage.appendChild(el);
      if(++portState.entities>8){ const old=stage.querySelector('.entity-marker'); if(old) old.remove(); }
      pushEvent('world', '干预台', `实体「${name}」落入世界`, 'public');
      say(`干预 · 实体「${name}」`);
      break;
    }
    case 'create_relationship': {
      const A=portAgent(+v.a), B=portAgent(+v.b); if(!A||!B||A===B) break;
      const NS='http://www.w3.org/2000/svg';
      const line=document.createElementNS(NS,'line');
      line.setAttribute('class','rel-line');
      const tag=document.createElementNS(NS,'text');
      tag.setAttribute('class','rel-tag');
      tag.textContent=(v.label||'关联').slice(0,8);
      linkLayer.appendChild(line); linkLayer.appendChild(tag);
      portState.relations.push({aId:A.id, bId:B.id, until:now+20000, line, tag});
      pushEvent('world', '干预台', `${A.name} ↔ ${B.name}「${tag.textContent}」`, 'participants');
      say(`干预 · 关系 ${A.name}↔${B.name}`);
      break;
    }
    case 'set_wallet_access': {
      const a=portAgent(+v.agent); if(!a) break;
      if(v.action==='grant'){ a.walletBlockedUntil=0; say(`干预 · 恢复 ${a.name} 交易权`); }
      else{
        const dur=clamp(parseInt(v.duration)||60, 5, 600);
        a.walletBlockedUntil=now+dur*1000;
        say(`干预 · 收回 ${a.name} 交易权 ${dur}s`);
      }
      break;
    }
  }
  pushEvent('intervention', '干预台', effectSummary(e), 'participants');
}

/* -------- 干预计划底舱（React InterventionWorkspace 移植） -------- */
function effectUntil(e){   // 生效中效果的截止时刻（0 = 即时效果）
  switch(e.type){
    case 'set_market_status': return portState.haltedUntil;
    case 'set_account_freeze': {const a=portAgent(+e.vals.agent); return a?(a.frozenUntil||0):0;}
    case 'set_wallet_access': {const a=portAgent(+e.vals.agent); return a?(a.walletBlockedUntil||0):0;}
    case 'create_relationship': {const r=portState.relations.find(x=>x.aId===+e.vals.a&&x.bId===+e.vals.b); return r?r.until:0;}
    default: return 0;
  }
}
function planActive(p){
  return !p.terminated && p.effects.some(e=>e.until && now<e.until);
}
function portTerminatePlan(p){
  for(const e of p.effects){
    if(!e.until || now>=e.until) continue;
    switch(e.type){
      case 'set_market_status': portState.haltedUntil=0; break;
      case 'set_account_freeze': {const a=portAgent(+e.vals.agent); if(a) a.frozenUntil=0; break;}
      case 'set_wallet_access': {const a=portAgent(+e.vals.agent); if(a) a.walletBlockedUntil=0; break;}
      case 'create_relationship': {const r=portState.relations.find(x=>x.aId===+e.vals.a&&x.bId===+e.vals.b); if(r) r.until=0; break;}
    }
    e.until=0;
  }
  p.terminated=true;
  const s=Math.floor(now/1000);
  addLedger(`<i class="blk"></i>t+${s}s&nbsp;&nbsp;干预 · 计划 #${p.id} 提前终止&nbsp;&nbsp;#${hex(4,mrng)}…`);
  pushEvent('intervention', '干预台', `计划 #${p.id} 提前终止`, 'participants');
  renderPlans();
}
function renderPlans(){
  const el=$('plan-list');
  if(!portState.plans.length){
    el.innerHTML='<div class="port-empty">尚无干预计划。在左栏「干预效果」组队并提交。</div>';
    return;
  }
  el.innerHTML=portState.plans.map(p=>{
    const active=planActive(p);
    const st=p.terminated?['已终止','st-ended']:active?['生效中','st-active']:['已结束','st-done'];
    return `<div class="plan-card">`+
      `<div class="pc-head"><span class="pc-id">计划 #${p.id}</span>`+
      `<span class="pc-st ${st[1]}">${st[0]}</span>`+
      `<span class="pc-t">t+${Math.floor(p.at/1000)}s · ${p.effects.length} 项效果</span></div>`+
      `<div class="pc-effects">${p.effects.map(e=>{
        const d=EFFECT_DEFS[e.type];
        const left=e.until&&now<e.until?Math.ceil((e.until-now)/1000):0;
        return `<div class="pc-eff"><span class="effect-badge" style="border-color:${d.color};color:${d.color}">${d.label}</span>`+
          `<span class="q-sum">${portEsc(effectSummary(e))}</span>${left?`<span class="pc-left">余 ${left}s</span>`:''}</div>`;
      }).join('')}</div>`+
      (active?`<button class="pc-stop mono" data-id="${p.id}">提前终止</button>`:'')+
    `</div>`;
  }).join('');
  el.querySelectorAll('.pc-stop').forEach(b=>b.addEventListener('click',()=>{
    const p=portState.plans.find(x=>x.id===+b.dataset.id);
    if(p) portTerminatePlan(p);
  }));
}
function portOpenDock(){
  $('plan-dock').classList.remove('hidden');
  renderPlans();
}

/* -------- 舞台填充：成交量柱 / 深度地形 / 封存地环 / 名录 -------- */
function renderVolBars(){
  const g=$('vol-bars'); if(!g) return;
  const W=pulseSvg.clientWidth, H=pulseSvg.clientHeight;
  if(!W) return;
  const t0=now-45000, bucket=3000, n=15;
  const sums=new Array(n).fill(0), dirs=new Array(n).fill(0);
  for(const e of (stats.actionLog||[])){
    if(e.kind!=='trade'||e.at<t0) continue;
    const i=Math.min(n-1, Math.floor((e.at-t0)/bucket));
    sums[i]+=e.qty; dirs[i]+=e.dir*e.qty;
  }
  const max=Math.max(1,...sums);
  const bw=W/n*0.52;
  let html='';
  for(let i=0;i<n;i++){
    if(!sums[i]) continue;
    const h=5+(sums[i]/max)*(H*0.30);
    const x=(i+0.5)/n*W-bw/2;
    const col=dirs[i]>0?'rgba(111,162,135,.32)':dirs[i]<0?'rgba(176,112,95,.32)':'rgba(122,139,143,.28)';
    html+=`<rect x="${x.toFixed(1)}" y="${(H-h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${col}"/>`;
  }
  g.innerHTML=html;
}
function renderDepthTerrain(){
  const b=$('depth-bids'), k=$('depth-asks');
  if(!b||!k) return;
  const {bids, asks}=portState.book;
  if(!bids.length||!asks.length) return;
  const base=588, cx=500, maxW=330, maxH=62;
  const cum=arr=>{let s=0;return arr.map(o=>(s+=o.qty));};
  const cB=cum(bids), cA=cum(asks);
  const maxC=Math.max(cB[cB.length-1], cA[cA.length-1], 1);
  const mk=(c,dir)=>{
    let d=`M${cx},${base}`;
    c.forEach((v,i)=>{
      const x=cx+dir*(i+1)/c.length*maxW;
      d+=` L${x.toFixed(1)},${(base-(v/maxC)*maxH).toFixed(1)}`;
    });
    return d+` L${cx+dir*maxW},${base} Z`;
  };
  b.setAttribute('d', mk(cB,-1));
  k.setAttribute('d', mk(cA,+1));
}
function renderSealDial(){
  const d=$('seal-dial'); if(!d) return;
  const pct=clamp((1-(nextSealAt-now)/SEAL_PERIOD)*100, 0, 100);
  d.setAttribute('stroke-dasharray', `${pct.toFixed(1)} 100`);
}
const WATCH_STATE={idle:'观望',thinking:'思考',speaking:'发言',cooldown:'冷却',judging:'判定',leaving:'离场'};
function renderWatch(){
  const el=$('watch-strip'); if(!el) return;
  const trades=(stats.actionLog||[]).filter(e=>e.kind==='trade').length;
  const heatAbs=Math.abs(market.change(15));
  const temp=heatAbs>0.35?'躁动':heatAbs<0.08?'平静':'温和';
  el.textContent=`t+${Math.floor(now/1000)}s · 成交 ${trades} · 注入 ${infoHistory.length} · 温度 ${temp}`;
}
function renderRoster(){
  const el=$('roster'); if(!el) return;
  el.innerHTML=agents.filter(a=>a.state!=='leaving').map(a=>{
    const st=a.convo?'交谈':(WATCH_STATE[a.state]||a.state);
    const frozen=a.frozenUntil&&now<a.frozenUntil;
    const blocked=a.walletBlockedUntil&&now<a.walletBlockedUntil;
    return `<div class="ro-row" data-id="${a.id}">`+
      `<i class="ro-dot" style="background:${a.color}"></i>`+
      `<span class="ro-name">${portEsc(a.name)}</span>`+
      `<span class="ro-persona">${PERSONAS[a.persona].label}</span>`+
      `<span class="ro-state">${frozen?'冻结':blocked?'限权':st}</span></div>`;
  }).join('');
}

/* -------- 归档：封存快照（React BranchExplorer 简化移植） -------- */
const ARCHIVE_KEY='sandbox-archives-v1';
const archives=[];
function saveArchives(){
  try{ localStorage.setItem(ARCHIVE_KEY, JSON.stringify(archives.slice(0,20))); }catch(e){}
}
function loadArchives(){
  try{
    const raw=localStorage.getItem(ARCHIVE_KEY);
    if(raw) archives.push(...JSON.parse(raw));
  }catch(e){}
}
function portArchiveSeal(h, kind){
  archives.unshift({
    hash:h, kind:kind||'seal', t:Math.floor(now/1000),
    at:new Date().toLocaleString('zh-CN',{hour12:false}),
    scenario:scenario.name,
    price:+market.price.toFixed(2), volume:portState.volume,
    trades:(stats.actionLog||[]).filter(e=>e.kind==='trade').length,
    infos:infoHistory.length,
    agents:agents.filter(a=>a.state!=='leaving').length,
    lines:[...ledgerList.children].slice(0,8).map(c=>c.textContent.replace(/\s+/g,' ').trim()),
  });
  if(archives.length>20) archives.pop();
  saveArchives();
  if($('archive-tab').classList.contains('visible')) renderArchives();
}
function renderArchives(){
  const el=$('archive-list');
  el.innerHTML=archives.length?archives.map((a,i)=>`
    <div class="arch-row" data-i="${i}">
      <div class="arch-head"><span class="arch-hash">${a.kind==='manual'?'◈':'◇'} 0x${a.hash}</span><span class="arch-t">t+${a.t}s</span></div>
      <div class="arch-meta">价 ${a.price} · 量 ${a.volume.toLocaleString()} · 成交 ${a.trades} · 信息 ${a.infos} · ${a.agents} 棋子</div>
      <div class="arch-when">${portEsc(a.scenario||'')} · ${a.at||''}</div>
      <div class="arch-detail hidden">${(a.lines||[]).map(l=>`<div class="arch-line">${portEsc(l)}</div>`).join('')}</div>
    </div>`).join('')
    :'<div class="port-empty">尚无封存档案。世界每 90s 自动封存，或点上方按钮手动封存。</div>';
  el.querySelectorAll('.arch-row').forEach(r=>r.addEventListener('click',()=>{
    r.querySelector('.arch-detail').classList.toggle('hidden');
  }));
}

/* -------- 场景配置弹窗（React QuickStartPage 简化移植） -------- */
function wireScenarioModal(){
  $('scenario-btn').addEventListener('click', ()=>$('scenario-modal').classList.remove('hidden'));
  $('scenario-close').addEventListener('click', ()=>$('scenario-modal').classList.add('hidden'));
  $('scenario-modal').addEventListener('click', e=>{
    if(e.target.id==='scenario-modal') $('scenario-modal').classList.add('hidden');
  });
  $('scenario-apply').addEventListener('click', ()=>{
    scenario.name=($('sc-name').value||'').trim().slice(0,16)||'EPOCH ONE';
    scenario.seed=parseInt($('sc-seed').value,10)||20260725;
    scenario.agents=clamp(parseInt($('sc-agents').value,10)||6, 3, 12);
    scenario.price=Math.max(1, parseFloat($('sc-price').value)||100);
    scenario.vol=clamp(parseFloat($('sc-vol').value)||1, 0.3, 2.5);
    $('ledger-foot').textContent=`${scenario.name} · Injective EVM 语义 · 模拟演示`;
    $('scenario-modal').classList.add('hidden');
    resetWorld();
  });
}

/* -------- 移植层节拍：摄取 → 档位 → 指标 → 面板 -------- */
function portTick(){
  portIngest();
  if(performance.now()-portState.bookAt>700) genBook();
  renderMetricStrip();
  // 面板刷新
  if(!$('orderbook-slide').classList.contains('hidden')) renderOrderbookSlide();
  if($('events-tab').classList.contains('visible')) renderEvents();
  if(!$('plan-dock').classList.contains('hidden')) renderPlans();
  // 棋子状态外观
  for(const a of agents){
    a.el.root.classList.toggle('frozen', !!(a.frozenUntil&&now<a.frozenUntil));
    a.el.root.classList.toggle('wallet-blocked', !!(a.walletBlockedUntil&&now<a.walletBlockedUntil));
  }
  // 停牌外观
  const halted=now<portState.haltedUntil;
  pulseWrap.classList.toggle('halted', halted);
  const simTag=document.querySelector('.sim-tag');
  if(simTag) simTag.textContent=halted?'停牌':(source&&source.mode==='remote'&&remoteHealthy?'LIVE':'模拟');
  // 关系连线跟随
  for(let i=portState.relations.length-1;i>=0;i--){
    const r=portState.relations[i];
    const A=portAgent(r.aId), B=portAgent(r.bId);
    if(now>=r.until||!A||!B||A.state==='leaving'||B.state==='leaving'){
      r.line.remove(); r.tag.remove();
      portState.relations.splice(i,1); continue;
    }
    r.line.setAttribute('x1',A.pos.x); r.line.setAttribute('y1',A.pos.y-30);
    r.line.setAttribute('x2',B.pos.x); r.line.setAttribute('y2',B.pos.y-30);
    r.tag.setAttribute('x',(A.pos.x+B.pos.x)/2); r.tag.setAttribute('y',(A.pos.y+B.pos.y)/2-38);
  }
  // 市场温度三态（去素化：平静绿调 / 过热红调）
  const heatAbs=Math.abs(market.change(15));
  pulseWrap.classList.toggle('heat', !halted && heatAbs>0.35);
  pulseWrap.classList.toggle('calm', !halted && heatAbs<0.08);
  stage.classList.toggle('heat', !halted && heatAbs>0.35);
  stage.classList.toggle('calm', !halted && heatAbs<0.08);
  // 舞台填充层
  renderVolBars();
  renderDepthTerrain();
  renderSealDial();
  if($('inject-tab').classList.contains('visible')){
    renderWatch();
    renderRoster();
  }
}

/* -------- 标签页接线 -------- */
function wireTabs(containerSel, contentMap){
  const btns=document.querySelectorAll(containerSel+' .tab-btn');
  btns.forEach(btn=>btn.addEventListener('click', ()=>{
    btns.forEach(b=>b.classList.toggle('selected', b===btn));
    for(const [key, el] of Object.entries(contentMap)){
      el.classList.toggle('visible', key===btn.dataset.tab);
    }
    if(btn.dataset.tab==='events') renderEvents();
    if(btn.dataset.tab==='archive') renderArchives();
  }));
}

/* -------- 移植层初始化 / 复位 -------- */
function portInit(){
  $('metric-strip').classList.remove('hidden');
  $('ledger-foot').textContent=`${scenario.name} · Injective EVM 语义 · 模拟演示`;
  genBook();
  renderMetricStrip();
  // 左右栏标签
  wireTabs('#panel-tabs-left', {inject:$('inject-tab'), intervention:$('intervention-tab')});
  wireTabs('#panel-tabs-right', {ledger:$('ledger-tab'), events:$('events-tab'), archive:$('archive-tab')});
  // 侧滑标签
  document.querySelectorAll('.slide-tab-btn').forEach(btn=>btn.addEventListener('click', ()=>{
    document.querySelectorAll('.slide-tab-btn').forEach(b=>b.classList.toggle('selected', b===btn));
    ['overview','memory','decisions','trades'].forEach(k=>
      $('agent-slide-'+k).classList.toggle('visible', k===btn.dataset.slideTab));
  }));
  // 指标按钮 ↔ 订单簿侧滑
  $('toggle-metrics').addEventListener('click', portToggleOrderbook);
  // 棋子点击 → Agent 审计
  pawnLayer.addEventListener('click', e=>{
    const pawnEl=e.target.closest('.pawn');
    if(!pawnEl) return;
    const a=agents.find(x=>x.el.root===pawnEl);
    if(a) openAgentSlide(a);
  });
  // Esc 关闭侧滑
  window.addEventListener('keydown', e=>{ if(e.key==='Escape') portCloseAll(); });
  // 干预效果表单
  $('effect-type').addEventListener('change', renderEffectFields);
  renderEffectFields();
  $('add-effect-btn').addEventListener('click', ()=>{
    const draft=readEffectDraft();
    if(draft.type==='publish_information' && !(draft.vals.text||'').trim()) return;
    if(draft.type==='create_world_entity' && !(draft.vals.name||'').trim()) return;
    portState.queue.push(draft);
    renderQueue();
  });
  $('submit-intervention-btn').addEventListener('click', ()=>{
    const pendingEffects=portState.queue.filter(e=>e.status==='待提交');
    if(!pendingEffects.length) return;
    const plan={id:++portState.seq, at:now, effects:pendingEffects, terminated:false};
    portState.plans.unshift(plan);
    pendingEffects.forEach(e=>{ applyEffect(e); e.until=effectUntil(e); e.status='已应用'; });
    renderQueue();
    portOpenDock();
  });
  // 事件搜索
  $('event-search').addEventListener('input', renderEvents);
  $('event-visibility').addEventListener('change', renderEvents);
  // 名录点击 → Agent 审计
  $('roster').addEventListener('click', e=>{
    const row=e.target.closest('.ro-row');
    if(!row) return;
    const a=portAgent(+row.dataset.id);
    if(a) openAgentSlide(a);
  });
  // 归档
  loadArchives();
  $('archive-now').addEventListener('click', ()=>{
    portArchiveSeal(hex(10,mrng), 'manual');
    const s=Math.floor(now/1000);
    addLedger(`<i class="blk"></i>t+${s}s&nbsp;&nbsp;手动封存快照&nbsp;&nbsp;#${hex(4,mrng)}…`);
    renderArchives();
  });
  // 计划底舱 + 场景弹窗
  $('plan-dock-close').addEventListener('click', ()=>$('plan-dock').classList.add('hidden'));
  wireScenarioModal();
  setInterval(portTick, 500);
}
function portReset(){
  portState.holdings.clear();
  portState.volume=0;
  portState.seenActions=0;
  portState.seenInfos=0;
  portState.events.length=0;
  portState.queue.length=0;
  portState.plans.length=0;
  portState.relations.forEach(r=>{ r.line.remove(); r.tag.remove(); });
  portState.relations.length=0;
  portState.haltedUntil=0;
  stage.querySelectorAll('.entity-marker').forEach(el=>el.remove());
  portState.entities=0;
  lastMetricPrice=null;
  renderQueue();
  genBook();
  portCloseAll();
}

/* ---------------- 主循环 ---------------- */
let lastFrame=performance.now(), lastSample=0;
function frame(t){
  const dt=Math.min(120, t-lastFrame); lastFrame=t;
  if(!paused && !standby){
    now+=dt;
    const halted = now < portState.haltedUntil;
    if(!halted) market.tick(dt);
    if(now-lastSample>=40){ market.push(); lastSample=now; }
    for(const a of agents.slice())
      if(!a.convo && a.state!=='leaving' && a.nextAt && now>=a.nextAt) advance(a);
    for(const c of convos.slice()) if(now>=c.stepAt) stepConvo(c);
    for(let i=pending.length-1;i>=0;i--)
      if(now>=pending[i].at){ const p=pending.splice(i,1)[0]; p.fn(); }
    if(!halted) processActions();
    if(now>=nextSealAt){ commitRoot(); nextSealAt+=SEAL_PERIOD; }
    stage.classList.toggle('quiet', now-lastSpeechAt>20000);   // 空场雾起
    if(source && source._cb) source._cb(source.getProjection());
  }
  renderPulse();   // 候场/暂停时也渲染：冻结的历史线保持可见
  renderTop();
  requestAnimationFrame(frame);
}

/* ---------------- 启动 ---------------- */
window.addEventListener('resize', relayout);
window.addEventListener('load', ()=>{
  // 迭代 C：?source=remote&branch={id} 启用 RemoteSource，否则 MockSource
  const qs=new URLSearchParams(location.search);
  source = (qs.get('source')==='remote' && qs.get('branch'))
    ? new RemoteSource(qs.get('branch'))
    : new MockSource();
  source.start();
  updateModeTag();
  initWorld();
  portInit();
  requestAnimationFrame(frame);
});

/* 世界成形：预填 46s 市场历史（覆盖整个 45s 窗口，首帧即满幅），棋子入场 */
function initWorld(){
  market.price=scenario.price; market.anchor=scenario.price;
  for(let t=-46000;t<0;t+=50){ market.tick(50); market.samples.push({t, p:market.price}); }
  relayout();
  for(let i=0;i<scenario.agents;i++) spawnAgent(i, true);
  // 启幕后 5s 内保底一次交谈（验收用）
  pending.push({at:5200, fn:()=>{
    const idle=agents.filter(a=>a.state==='idle'&&!a.convo);
    if(idle.length>=2) startConvo(idle[0], idle[1]);
  }});
  addLedger(`<i class="blk"></i>t+0s&nbsp;&nbsp;world init&nbsp;&nbsp;#${hex(4,mrng)}…`);
}

/* 候场 → 启幕 */
function startWorld(){
  if(!standby) return;
  standby=false;
  $('standby-veil').classList.add('gone');
}

/* 一键回到候场态：清场、重建种子、世界重新成形并冻结 */
function resetWorld(){
  pending.length=0; actionQueue.length=0;
  for(const c of convos.slice()) endConvo(c, true);
  convos.length=0;
  stage.classList.remove('focus','quiet');
  for(const a of agents.slice()){ hideBubble(a); a.el.root.remove(); }
  agents.length=0; agentSeq=0;
  infoList.innerHTML=''; ledgerList.innerHTML='';
  infoHistory.length=0;
  infoSeq=0; lastInfoKw=null; lastSpeechAt=0; lastActionAt=-99999;
  stats.think=stats.speak=stats.convo=stats.action=0;
  stats.actionAt=[]; stats.actionLog=[];
  mrng=mulberry32(scenario.seed);
  market.price=scenario.price; market.anchor=scenario.price; market.impulse=0; market.samples.length=0;
  viewMid=null; viewRange=null;
  now=0; nextSealAt=SEAL_PERIOD;
  $('agent-slider').value=scenario.agents;
  portReset();
  initWorld();
  standby=true;
  $('standby-veil').classList.remove('gone');
  $('pause-btn').textContent='暂停'; paused=false;
}

$('start-btn').addEventListener('click', startWorld);
$('reset-btn').addEventListener('click', resetWorld);
window.addEventListener('keydown', e=>{
  if(!standby) return;
  if(e.code!=='Space'&&e.code!=='Enter') return;
  const ae=document.activeElement;
  if(ae && (ae.tagName==='TEXTAREA'||ae.tagName==='INPUT'||ae.tagName==='SELECT')) return;
  e.preventDefault();
  startWorld();
});

/* ---------------- 验收钩子（只读统计 + 可编程注入） ---------------- */
window.__sandbox={ stats, agents, market, inject,
  now:()=>now, setPaused:v=>{paused=v;},
  standby:()=>standby, startWorld, resetWorld,
  pulseView:()=>({mid:viewMid, range:viewRange}),
  source:()=>source, remoteHealthy:()=>remoteHealthy,
  convos,
  closeSlidePanels:portCloseAll,
  port:{ openAgent:id=>{const a=portAgent(id); if(a) openAgentSlide(a);},
         toggleOrderbook:portToggleOrderbook,
         openDock:portOpenDock,
         events:()=>portState.events,
         plans:()=>portState.plans,
         archives:()=>archives,
         book:()=>portState.book,
         holdings:()=>portState.holdings },
  forceConvo:(i,j,script)=>{
    const A=agents[i], B=agents[j];
    if(A&&B&&!A.convo&&!B.convo&&A.state==='idle'&&B.state==='idle')
      startConvo(A,B,script);
  } };
