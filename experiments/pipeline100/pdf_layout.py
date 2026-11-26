from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

WIDTH,HEIGHT=A4
M=42
TEXT='#172F3C';MUTED='#465C66';TEAL='#006A65';LIGHT='#E8F3EF';LINE='#D0DFDC';CREAM='#F4F6F4'
FONT='KoreanBody'
pdfmetrics.registerFont(TTFont(FONT,'/System/Library/Fonts/Supplemental/AppleGothic.ttf'))
def sw(text,size):return pdfmetrics.stringWidth(str(text),FONT,size)
def lines(text,width,size):
    result=[]
    for para in str(text).split('\n'):
        if not para:
            result.append('');continue
        buf=''
        for word in para.split(' '):
            candidate=buf+' '+word if buf else word
            if sw(candidate,size)<=width:
                buf=candidate;continue
            if buf:result.append(buf);buf=''
            for ch in word:
                if buf and sw(buf+ch,size)>width:result.append(buf);buf=''
                buf+=ch
        if buf:result.append(buf)
    return result or ['']

class Report:
    def __init__(self,path):
        self.c=Canvas(str(path),pagesize=A4,pageCompression=1)
        self.c.setTitle('질문에서 코드까지 · 100문항 멀티에이전트 비교')
        self.c.setAuthor('학술제 멀티에이전트 실험 · 연구 기록')
        self.y=0;self.n=0
    def draw(self,x,y,text,size=10,color=TEXT,align='left',font=FONT):
        self.c.setFillColor(colors.HexColor(color));self.c.setFont(font,size)
        fn={'left':self.c.drawString,'right':self.c.drawRightString,'center':self.c.drawCentredString}[align]
        fn(x,HEIGHT-y,str(text))
    def rect(self,x,y,w,h,color):
        self.c.setFillColor(colors.HexColor(color));self.c.rect(x,HEIGHT-y-h,w,h,fill=1,stroke=0)
    def page(self,title,section):
        self.n+=1;self.rect(0,0,WIDTH,7,TEAL)
        self.draw(M,35,'학술제 연구 기록  /  '+section,9,TEAL)
        self.draw(WIDTH-M,35,'2026. 11. 26.',9,MUTED,'right')
        self.draw(M,79,title,25)
        self.y=104
    def end(self):
        if self.y>795:raise ValueError(f'{self.n}쪽 본문이 하단을 넘었습니다. {self.y}')
        self.rect(M,807,WIDTH-M*2,0.6,LINE)
        self.draw(M,822,'멀티에이전트 비교 연구   ·   100문항 진단 표본',8,MUTED)
        self.draw(WIDTH-M,822,str(self.n),9,MUTED,'right');self.c.showPage()
    def para(self,text,size=11,color=TEXT,leading=17,gap=9):
        for line in lines(text,WIDTH-2*M-2,size):
            self.draw(M,self.y,line,size,color);self.y+=leading
        self.y+=gap
    def h(self,title):
        self.y+=5;self.draw(M,self.y,title,14,TEAL);self.y+=22
    def note(self,text):
        linez=lines(text,WIDTH-2*M-27,10)
        h=len(linez)*15+14
        self.rect(M,self.y-9,WIDTH-2*M,h,LIGHT)
        for i,txt in enumerate(linez):self.draw(M+12,self.y+5+i*15,txt,10,TEXT)
        self.y+=h+9
    def table(self,names,rows,widths,size=9.1,row=18,align=None,accent=(),wrap=False):
        w=WIDTH-M*2; widths=[x*w/sum(widths) for x in widths]
        align=align or ['left',*['right']*(len(names)-1)]
        def one(vals,head=False,highlight=False,strip=False):
            fields=[lines(str(v),widths[i]-11,size) if wrap else [str(v)] for i,v in enumerate(vals)]
            height=max(row,max(map(len,fields))*(size+3)+6)
            if head or highlight or strip:self.rect(M,self.y-11,w,height,TEAL if head else LIGHT if highlight else CREAM)
            x=M
            for j,field in enumerate(fields):
                for k,txt in enumerate(field):
                    chosen=size
                    if not wrap and sw(txt,chosen)>widths[j]-9:
                        chosen=max(6.2,(widths[j]-9)*chosen/sw(txt,chosen))
                    alg=align[j];pos=x+5 if alg=='left' else x+widths[j]-5 if alg=='right' else x+widths[j]/2
                    self.draw(pos,self.y+1+k*(size+3),txt,chosen,'#FFFFFF' if head else TEXT,alg)
                x+=widths[j]
            self.y+=height
        one(names,True)
        for j,data in enumerate(rows):one(data,highlight=j in accent,strip=bool(j%2))
        self.y+=9
    def save(self):self.c.save()

