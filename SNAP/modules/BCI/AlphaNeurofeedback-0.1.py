# -*- coding: UTF-8 -*-

'''
Procedura: AlphaNeurofeedback
Autor: Krzysztof Kutt, 2016

Cel procedury: Trening asymetrii przedczołowej alfy u sportowców
               (zwiększenie aktywności lewej półkuli -> więcej
               pozytywnych emocji -> lepsze wyniki) 

Budowa procedury (obsługuje całą jedną sesję z badanym):
  1. kalibracja (ustalenie aktualnego poziomu alfy jako punktu wyjścia):
     badany tylko patrzy na punkt fiksacji
  2. blok kilkuminutowy, w czasie którego badany skupia się na punkcie
     fiksacji i jego zadaniem jest przesunięcie wyświetlanego słupka
     w górę
  3. po każdym bloku następuje chwila przerwy (do naciśnięcia spacji)

Sterowanie:
  * Esc - wyłączenie procedury;
  * F2 - przerwanie procedury (pozostaje szary ekran);
  * F1 - rozpoczęcie procedury (na samym początku albo
         gdy przerwana klawiszem F2);
  * Spacja - uruchomienie + wznowienie po przerwie
  * Enter - gdy chcemy wyjść z aktualnego bloku i przeskoczyć do przerwy;
            w czasie kalibracji: przerywa i wykorzystuje poprzednie wartości
            asymKalibracja i asymSkalar (przydatne np. po restarcie procedury)
  * Backspace - gdy chcemy wrócić do przerwy przed aktualnym blokiem

Trzy warunki:
  1. Zwykły -- próg ustalony na 0 (równowaga między półkulami);
               pożądana przewaga aktywności prawej
  2. Adaptacyjny -- próg może być wyższy/niższy od 0); wartość progu dla sesji X
                    jest wyliczana na koniec sesji X-1; jest to próg poniżej
                    którego w sesji X-1 znalazło się z wartości, gdzie z jest
                    współczynnikiem szybkości adaptacji, np. dla z = 70%
                    próg na sesję X zostanie ustalony na poziomie poniżej którego
                    znalazło się 70% wartości w sesji X-1
  3. Fake -- bez udziału EEG (losowe zmiany wykresu)

Powiązane moduły:
  - AlphaNeurofeedback w BCILAB -> zbiera EEG, analizuje w czasie
    rzeczywistym i przekazuje wartość asymetrii alfy
    (0 dla równowagi półkul; <0 przewaga alfy lewej / aktywności prawej;
    >0 przewaga alfy prawej / aktywności lewej)
  - Lab Stream Layer --> narzędzie/protokół do przesyłania przez sieć
    aktualnego poziomu asymetrii (od BCILAB do tej procedury)
  - Lab Recorder (udostępniany z Lab Stream Layer) -> osobne narzędzie
    do zapisu w jednym pliku

Zbierane dane:
  - W tej procedurze (w pliku badani\ImięNazwisko.osb):
    * parametry procedury (ilość i długość bloków)
    * przypisanie badanego do warunku badawczego
    * wartości wyliczone w trakcie kalibracji
    * statystyki sesji (min, max, std, mean asymetria)
    * skuteczność badanego (szybkość osiągnięcia progu, czas powyżej progu)
    * w warunku fake:
      * parametry sesji fake
      * statystyki wyświetlanych fake danych
    * w warunku adaptacyjnym:
      * skuteczność badanego w odniesieniu do zmienionego progu
      * wyliczony próg na kolejną sesję
  - W innych miejscach:
    * plik ImięNazwisko.sesjaXX.xdf: EEG + triggery + wszystkie poziomy
      asymetrii
      FIXME: sprawdzić czy te wszystkie poziomy będą się dobrze
             zapisywać i wyświetlać w BrainVision / EEGLAB

FIXME: Triggery:
  * xxx - Początek kalibracji
  * xxx - Początek bloku/koniec przerwy
  * xxx - Koniec bloku/początek przerwy

Konfiguracja:
  * wartości domyślne znajdują się poniżej w __init__
  * mogą zostać nadpisane w pliku study.cfg
  * wszystko może zostać nadpisane w pliku badanego ImieNazwisko.osb
    
  * równolegle można konfigurować sposób wyświetlania:
    pliki fullscreen.prc, windowed.prc w folderze study

'''

from framework.latentmodule import LatentModule
import os, traceback, time, numpy
from random import randint

from pylsl.pylsl import StreamInlet, resolve_byprop

## do komunikatów dla badacza na początku:
from Tkinter import Tk, Label, Entry, Button, W
import tkMessageBox
from tkFileDialog import askopenfilename


class Main(LatentModule):
    
    def __init__(self):
        LatentModule.__init__(self)
        
        # przeładowanie kodowania na utf, żeby działały komunikaty
        # (Eclipse domyślnie ma utf, więc nie bylo tego widać wcześniej)
        import sys
        reload(sys).setdefaultencoding("utf-8")
        
        '''
        KONFIGURACJA BADANIA 
        (może zostać nadpisana w pliku .cfg danego study)
        
        folderBadani - folder z plikami konfiguracyjnymi osób badanych
        dlugKalibracji - czas trwania bloku kalibracji (w minutach)
        dlugBloku - czas trwania pojedynczego bloku (w minutach)
        iloscBlokow - ilość bloków składających się na całą sesję 
        poziomWysokosc - maksymalna wysokość wyświetlanego paska
        poziomSzerokosc - szerokość wyświetlanego paska
        poziomKolorOK, poziomKolorZLY - kolor paska, gdy jest powyżej/poniżej 0
        szybkoscAdaptacji - współczynnik procentowy (opisany szczegółowo wyżej)  
        '''
        self.folderBadani = 'studies\\Neurofeedback\\badani'
        self.dlugKalibracji = 0.1    # FIXME: zmienić na 1.0
        self.dlugBloku = 0.1         # FIXME: zmienić na 6.0
        self.iloscBlokow = 5
        self.poziomWysokosc = 0.5
        self.poziomSzerokosc = 0.05
        self.poziomKolorOK = [40.0/255.0, 215.0/255.0, 40.0/255.0, 1]
        self.poziomKolorZLY = [215.0/255.0, 40.0/255.0, 40.0/255.0, 1]
        self.szybkoscAdaptacji = 0.7
        
        
        '''
        WARTOŚCI DLA DANEJ OSOBY BADANEJ
        (mogą zostać nadpisane w pliku .osb danej osoby badanej)
        
        warunek - 1 = Zwykły; 2 = Adaptacyjny; 3 = Fake (szczegółowy
                  opis znajduje się na początku skryptu)
                  wartość domyślna = losowanie dla nowych badanych;
                  dla kolejnych sesji po prostu wczytujemy wartość
                  z pliku konfiguracyjnego danej osoby badanej
        zadanyProg - próg jaki badany ma osiągnąć w sesji
                    (domyślnie próg jest ustalony na zero; w warunku
                    z adaptacją jest zmienny)
        nrSesji - aktualny numer sesji (1 dla nowej osoby badanej)
        '''
        self.warunek = randint(1,3)
        self.zadanyProg = 0
        self.nrSesji = 1
        
        
        '''
        INNE WARTOŚCI GLOBALNE WYKORZYSTYWANE W PROCEDURZE
        
        plikBadanego - ścieżka bezwzględna do pliku .osb badanego
        asymALL - zbiór wszystkich wartości asymetrii w trakcie sesji
                  (tylko w trakcie bloków treningowych)
        asymSkalar - wspolczynnik skalowania wartosci z BCI do wysokości
                     wyswietlanego paska (wyliczany na podstawie wartości
                     z kalibracji i zadanego progu)
        asymKalibracja - wartość asymetri wyliczona podczas kalibracji
        czasNaRysowanie - opóźnienie po rysowaniu punktu fiksacji
                          i prostokąta, aby zdążyły się pojawić na ekranie
        wcisnietyKlawisz - obsługa klawiszy do sterowania procedurą
        '''
        self.plikBadanego = ""
        self.asymALL = []
        self.asymSkalar = 0.5
        self.asymKalibracja = 0.0
        self.czasNaRysowanie = 0.1
        self.wcisnietyKlawisz = ""
        
        
        ''' przypisanie zdarzeń dla obsługiwanych klawiszy '''
        self.accept("enter", self.obsluzKlawisz, ["enter"])
        self.accept("backspace", self.obsluzKlawisz, ["backspace"])


        ## FIXME: inicjalizacja karty do triggerów!


    def run(self):
        ''' ----------------------------------------------------------------- 
            -------------------- OBSŁUGA PLIKÓW BADANYCH --------------------
            ----------------------------------------------------------------- '''
        Tk().withdraw() # nie chcemy GUI Tinkera, to nie pozwala głównemu oknu się pojawić
        
        result = tkMessageBox.askquestion("Konfiguracja", "Czy to jest pierwsza sesja osoby badanej?",
                                          icon='question')
        if result == 'yes':
            """ pierwsza sesja - podajemy nazwę pliku + losujemy warunek """
            top = Tk()
            
            Label(top, text="Wprowadz nazwe pliku uzytkownika w formacie ImieNazwisko\n" + 
                  "(bez spacji i polskich znakow, imie i nazwisko zacznij od duzej litery).\n" + 
                  "Np. LukaszNowak",  font=("Times New Roman", 13)).grid(row=0,columnspan=2)
            E1 = Entry(top, bd = 3, width=40)
            E1.grid(row=1)
            Button(top, text="OK", width=15, command=lambda: self.check_filename(top, E1)).grid(row=1,
                                                                    column=1, sticky=W, pady=4)
            top.wm_title("Tworzenie pliku nowej osoby badanej")
            
            # wyśrodkuj okienko
            top.update_idletasks()
            w = top.winfo_screenwidth()
            h = top.winfo_screenheight()
            size = tuple(int(_) for _ in top.geometry().split('+')[0].split('x'))
            x = w/2 - size[0]/2
            y = h/2 - size[1]/2
            top.geometry("%dx%d+%d+%d" % (size + (x, y)))
            
            # brak możliwości zmiany rozmiaru
            top.resizable(0,0)
            
            # pętla nieskończona (działa dopóki badany nie poda właściwej nazwy pliku)
            top.mainloop()
            
            # tutaj już mamy ustaloną nazwę pliku (z funkcji sprawdzającej w GUI)
            # tworzymy ten plik...
            open(self.plikBadanego, 'a').close()
            # ... i zapisujemy początkowe ustawienia osoby badanej
            self.write_to_file("warunek = " + str(self.warunek) + '\n',
                               "Ustawienia poczatkowe")

        else:
            """ kolejna sesja - wybieramy plik danej osoby i wczytujemy dane """
            while self.plikBadanego == "":
                self.plikBadanego = askopenfilename(initialdir = self.folderBadani,
                                                    filetypes = [('Pliki osób badanych', '.osb')])
                if self.plikBadanego == "":
                    tkMessageBox.showerror("Uwaga", "Wybierz plik osoby badanej!")
            
            # wczytujemy dane (na podstawie kodu z launcher.py)
            try:
                if not os.path.exists(self.plikBadanego):
                    print 'Plik badanego "' + self.plikBadanego + '" nie znaleziony.'
                else:
                    with open(self.plikBadanego,'r') as f:
                        print 'Wczytywanie parametrow z pliku badanego...',
                        for line in f.readlines():
                            exec line in self.__dict__
                        print 'Zrobione.'
            except Exception,e:
                print 'Problem z wczytywaniem informacji z pliku "' + self.plikBadanego + '".'
                print e
                traceback.print_exc()
        
        # zapisywanie informacji o początku sesji do pliku
        self.write_to_file('\n\n##### Początek sesji ' + str(self.nrSesji) + ' -- ' +
                           time.strftime("%d.%m.%Y %H:%M:%S") + ' ##### \n' +
                           '### Parametry sesji:\n' + 
                           '# dlugKalibracji = ' + str(self.dlugKalibracji) +
                           '\n# iloscBlokow = ' + str(self.iloscBlokow) + 
                           '\n# dlugBloku = ' + str(self.dlugBloku) + 
                           '\n# zadanyProg = ' + str(self.zadanyProg) + '\n',
                           'Informacje o nowej sesji')
        #FIXME: zapisywanie parametrów Fake Feedback do pliku
        
        
        ''' ----------------------------------------------------------
            -------------------- POCZATEK BADANIA --------------------
            ---------------------------------------------------------- '''
        # uzyskanie dostępu do poziomów alfy przesyłanych przez sieć
        streams = resolve_byprop(prop = 'name', value = 'BCIAlphaLevel',
                                 timeout = 3)
        while len(streams) == 0:
            self.write("UWAGA! Procedura na laptopie nie zostala wlaczona!")
            streams = resolve_byprop(prop = 'name', value = 'BCIAlphaLevel',
                                     timeout = 3)
        inlet = StreamInlet(streams[0])
        
        self.write('Witaj! To jest Twoja ' + str(self.nrSesji) + '. sesja.' +
                   u'\nZaczniemy ją już niedługo!','space')
        print "PROCEDURA ZAINICJALIZOWANA! NACISNIJ SPACJE, ABY ROZPOCZAC"
        
        ''' ----------------------------------------------------
            -------------------- KALIBRACJA --------------------
            ---------------------------------------------------- 
            zbieramy aktualny poziom różnicy alfy i wyliczamy średni poziom
            jako punkt 50% wysokości paska (aby była możliwość ruszać się
            w górę i w dół w trakcie procedury) '''        
        print("Poczatek kalibracji...  "),
        ## FIXME: trigger: startuje kalibracja
        
        ## FIXME: dawac tez trigger w momencie zmiany poziomu alfy
        ## (zawsze ten sam)
        
        for k in range(5,0,-1):
            self.write('Kalibracja rozpocznie się za '+str(k)+'.'+
                       '\nProszę patrz na + pośrodku ekranu i postaraj' +
                       ' się nie ruszać.')
        
        punktFiks = self.crosshair(100000,size=0.2,width=0.005,block=False)
        self.sleep(self.czasNaRysowanie)  # czas na pojawienie się punktu fiksacji
        
        self.asymALL = []
        inlet.pull_chunk()  # wyciągnij wszystkie próbki, które były do tej pory
        self.wcisnietyKlawisz = ""  # skasuj klawisze wciśnięte do tej pory
        koniecCzasu = time.time() + 60.0*self.dlugKalibracji
        
        while time.time() < koniecCzasu:
            # pobierz kolejny poziom alfy
            sample,_timestamp = inlet.pull_sample()
            self.asymALL.append(sample[0])
            
            self.sleep(self.czasNaRysowanie)  # czas na obsluge ew. klawisza
            
            # przerywamy zbieranie danych do kalibracji
            if self.wcisnietyKlawisz == "enter":
                break
                
        if self.wcisnietyKlawisz == "enter":
            #nie robimy nic; do kalibracji zostaje wartosc poprzednia,
            #wyliczona podczas poprzedniej sesji i zapisana w pliku (ew. domyślna)
            #(na wypadek np. przerwanej procedury, która została wznowiona)
            self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
            print("Kalibracja przerwana. Uzyte poprzednie wartosci")
        else:    # wyliczamy skalar do przeliczania wartości z BCI na wysokość paska
            self.asymKalibracja = numpy.mean(self.asymALL)
            print("Asymetria wyliczona: " + str(self.asymKalibracja))
            
            ## chcemy, żeby poziom z kalibracji oznaczał 50% wysokości paska
            if self.asymKalibracja - self.zadanyProg == 0:
                # nie mamy jak wyliczyć skalara, więc zostaje domyślny
                pass
            else:
                skalarTemp = (0.5 * self.poziomWysokosc) / (self.asymKalibracja - 
                                                           self.zadanyProg)
                if skalarTemp < 0:   #skalar musi byc dodatni
                    skalarTemp = -skalarTemp
                self.asymSkalar = skalarTemp
            
            #zapisujemy wyliczone wartości do pliku
            self.write_to_file("asymKalibracja = " + str(self.asymKalibracja) +
                               "\nasymSkalar = " + str(self.asymSkalar) + '\n',
                               "Dane kalibracji")
        
        
        ''' ------------------------------------------------------------
            -------------------- BLOK NEUROFEEDBACK --------------------
            ------------------------------------------------------------ '''
        
        self.asymALL = []   #usuwamy dane z kalibracji
        prost = None
        
        punktFiks.destroy()  #usuwamy punkt fiksacji podczas instrukcji
        blok = 1
        while blok <= self.iloscBlokow:
            for k in range(5,0,-1):
                self.write('Blok ' + str(blok) + ' z ' + str(self.iloscBlokow) + 
                           ' rozpocznie się za '+ str(k)+'.'+
                           '\n\nTwoim zadaniem jest sprawienie, aby słupek' +
                           ' na ekranie sięgał jak najwyżej.'
                           '\nProszę patrz na + pośrodku ekranu i postaraj' +
                           ' się nie ruszać.')
            
            punktFiks = self.crosshair(100000,size=0.2,width=0.005,block=False)
            
            inlet.pull_chunk()  # wyciągnij wszystkie próbki, które były w czasie przerwy
            self.wcisnietyKlawisz = ""  # skasuj klawisze z przerwy
            koniecCzasu = time.time() + 60.0*self.dlugBloku
            
            ## FIXME: marker - początek bloku!
            
            while time.time() < koniecCzasu:
                # pobierz kolejny poziom alfy
                sample,_timestamp = inlet.pull_sample()
                self.asymALL.append(sample[0])
                
                ''' WYLICZ ROZMIAR PROSTOKATA '''
                if self.warunek == 3:   ## FAKE FEEDBACK
                    # FIXME: DO PRZYGOTOWANIA!
                    poziom = 0
                    pass
                
                else:  ## PRAWDZIWY FEEDBACK
                    poziom = (sample[0]-self.zadanyProg) * self.asymSkalar
                
                #zaktualizuj prostokat:
                if poziom < 0:
                    kolor = self.poziomKolorZLY
                else:
                    kolor = self.poziomKolorOK
                if prost is not None:
                    prost.destroy()  #skasuj poprzedni prostokąt
                prost = self.rectangle([-self.poziomSzerokosc,self.poziomSzerokosc,
                                       max(0,poziom),min(0,poziom)],0,block=False,
                                       color=kolor)
                self.sleep(self.czasNaRysowanie) #czas na przerysowanie ekranu
                
                # przerywamy blok i idziemy do kolejnego
                if self.wcisnietyKlawisz == "enter":
                    self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
                    break
                # przerywamy blok i zaczynamy go od początku
                elif self.wcisnietyKlawisz == "backspace":
                    blok -= 1
                    self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
                    break
            
            prost.destroy()  # usuwamy na czas przerwy
            punktFiks.destroy()  # usuwamy na czas przerwy
        
            ## przerwa (wyświetlenie komunikatu i oczekiwanie na spację)
            ## nie wyświetlamy jej jeśli jest to ostatni blok
            ## FIXME: marker przerwa
            
            if blok < self.iloscBlokow:
                self.write('Za Tobą już ' + str(blok) + ' z ' +
                           str(self.iloscBlokow) + ' bloków. Czas na' +
                           ' chwilę przerwy!','space')
            blok += 1   # przechodzimy do kolejnego bloku
            
        
        ''' --------------------------------------------------------------
            -------------------- KONIEC: ZAPIS DANYCH --------------------
            -------------------------------------------------------------- '''
        
        napisKoniec = self.write('To już koniec na dzisiaj. Dziękujemy za' +
                                 ' udział w treningu!\n\n ', duration = 0,
                                 block = False)
        
        sredniaAsymetria = numpy.mean(self.asymALL)
        minAsymetria = numpy.min(self.asymALL)
        maxAsymetria = numpy.max(self.asymALL)
        odchStandAsym = numpy.std(self.asymALL)
        
        self.write_to_file("### Statystyki sesji:\n" + 
                           "# sredniaAsymetria = " + str(sredniaAsymetria) +
                           "\n# minAsymetria = " + str(minAsymetria) + 
                           "\n# maxAsymetria = " + str(maxAsymetria) + 
                           "\n# odchStandAsym = " + str(odchStandAsym) + "\n",
                           "Statystyki sesji")
        
        if self.warunek == 3:
            ## FIXME: wyliczyć te wartości!
            sredniaAsymetriaFAKE = 0.0
            minAsymetriaFAKE = 0.0
            maxAsymetriaFAKE = 0.0
            odchStandAsymFAKE = 0.0
            
            self.write_to_file("### Statystyki wyświetlanych wartości w sesji FAKE:\n" + 
                               "# sredniaAsymetriaFAKE = " + str(sredniaAsymetriaFAKE) +
                               "\n# minAsymetriaFAKE = " + str(minAsymetriaFAKE) + 
                               "\n# maxAsymetriaFAKE = " + str(maxAsymetriaFAKE) + 
                               "\n# odchStandAsymFAKE = " + str(odchStandAsymFAKE) + "\n",
                               "Statystyki sesji FAKE")
        
        czasPowyzejProgu0 = len([i for i in self.asymALL if i >= 0.0])
        procPowyzejProgu0 = (100.0 * czasPowyzejProgu0) / len(self.asymALL)
        if czasPowyzejProgu0 == 0:
            czasDoProgu0 = -1
            procDoProgu0 = -100.0
        else:    ## FIXME: to się źle wylicza!
            czasDoProgu0 = numpy.argmax(self.asymALL >= 0.0)
            procDoProgu0 = (100.0 * czasDoProgu0) / len(self.asymALL) 
        
        self.write_to_file("### Skuteczność:\n" + 
                           "## Pierwsze przekroczenie progu 0 (w sek i w %)\n" +
                           "# czasDoProgu0 = " + str(czasDoProgu0) + "\n" +
                           "# procDoProgu0 = " + str(procDoProgu0) + "%\n" +
                           "## Czas powyżej progu 0 (w sek i w %)\n" +
                           "# czasPowyzejProgu0 = " + str(czasPowyzejProgu0) + "\n" +
                           "# procPowyzejProgu0 = " + str(procPowyzejProgu0) + "%\n",
                           "Skutecznosc")
        
        if self.warunek == 2:
            czasPowyzejProguN = len([i for i in self.asymALL if i >= self.zadanyProg])
            procPowyzejProguN = (100.0 * czasPowyzejProguN) / len(self.asymALL)
            if czasPowyzejProguN == 0:
                czasDoProguN = -1
                procDoProguN = -100.0
            else:    ## FIXME: to się źle wylicza!
                czasDoProguN = numpy.argmax(self.asymALL >= self.zadanyProg)
                procDoProguN = (100.0 * czasDoProguN) / len(self.asymALL) 
            
            self.write_to_file("### Skuteczność w warunku adaptacyjnym (przesunięty próg):\n" + 
                               "## Pierwsze przekroczenie progu N (w sek i w %)\n" +
                               "# czasDoProguN = " + str(czasDoProguN) + "\n" +
                               "# procDoProguN = " + str(procDoProguN) + "%\n" +
                               "## Czas powyżej progu N (w sek i w %)\n" +
                               "# czasPowyzejProguN = " + str(czasPowyzejProguN) + "\n" +
                               "# procPowyzejProguN = " + str(procPowyzejProguN) + "%\n",
                               "Skutecznosc z przesunietym progiem")
                
        self.write_to_file("##### Koniec sesji " + str(self.nrSesji) + " -- " +
                           time.strftime("%d.%m.%Y %H:%M:%S") + ' ##### \n' + 
                           "\nnrSesji = " + str(self.nrSesji + 1) + '\n',
                           "Koniec zapisu sesji")
        if self.warunek == 2:
            self.asymALL.sort()
            nowyProg = self.asymALL[ int(self.szybkoscAdaptacji * len(self.asymALL))]
            self.write_to_file("zadanyProg = " + str(nowyProg) + "\n",
                               "Nowy prog w warunku adaptacji")
        
        
        #FIXME: zapisywanie poziomów alfy z całej sesji do plików
        #       np. ImieNazwisko.[sesja]1.[blok]1.alp
        # W pliku dawać nagłówek w komentarzu z datą i długością danego bloku
        # (gdyby długość miała się zmieniać)
        # Poziomy zapisywać jako:
        # asymNAGRANIE = [p1, p2, p3]
        # żeby później dało się wczytać po prostu wykonując daną linijkę
        # z pliku
        # w warunku FAKE zapisujemy który blok był przypisany do którego
        # pliku z zapisem!
        # 
        # FAKE FEEDBACK będzie polegał na odtwarzaniu bloku z pliku
        # jeśli braknie nam próbek (bo np. sesja nagrana trwała o 1-2 próbki
        # krócej) to cofamy się od końca tabeli w kierunku początku, żeby
        # cały czas była jakaś zmienność poziomu
        
        napisKoniec.destroy()
        self.write('To już koniec na dzisiaj. Dziękujemy za' +
                   ' udział w treningu!\n\n Dane sesji zostały zapisane.',
                   duration = 0,
                   block = False)



    """ ----------------------------------------------
        ------------  FUNKCJE POMOCNICZE  ------------
        ---------------------------------------------- """

    def check_filename(self, top, entry):
        """"Sprawdź czy plik o takiej nazwie już istnieje;
            Jeśli tak: komunikat
            Jeśli nie: utwórz plik
        """
        nazwaPliku = self.folderBadani + "\\" + entry.get() + ".osb"
        
        if len(entry.get()) < 5:
            tkMessageBox.showerror("Uwaga", "Nazwa pliku powinna zawierac co najmniej 5 znakow!")
        elif os.path.exists(nazwaPliku):
            tkMessageBox.showerror("Uwaga", "Plik o podanej nazwie juz istnieje!")
        else:
            self.plikBadanego = nazwaPliku
            top.withdraw()  #schowaj okienko
            top.quit()      #wyjdź z pętli GUI i wróć do procedury


    def write_to_file(self, text, comment):
        try:
            if not os.path.exists(self.plikBadanego):
                print 'Plik badanego "' + self.plikBadanego + '" nie znaleziony.'
            else:
                with open(self.plikBadanego,'a') as f:
                    print comment + " wpisywane do pliku...",
                    f.write(text)
                    print 'Zrobione.'
        except Exception,e:
            print 'Problem z zapisywaniem informacji do pliku "' + self.plikBadanego + '".'
            print e
            traceback.print_exc()


    def obsluzKlawisz(self, klawisz):
        self.wcisnietyKlawisz = klawisz
