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
  2. blok kilkuminutowy, w czasie którego badany stara się zebrać jak
     najwięcej punktów (czyli powinien jak najwyżej przesuwać słupek
     pojawiający się na ekranie)
  3. po każdym bloku następuje chwila przerwy (do naciśnięcia spacji)

Sterowanie:
  * Esc - wyłączenie procedury;
  * F2 - przerwanie procedury (pozostaje szary ekran);
  * F1 - rozpoczęcie procedury (na samym początku albo
         gdy przerwana klawiszem F2);
  * Spacja - uruchomienie + wznowienie po przerwie
  * Enter - gdy chcemy wyjść z aktualnego bloku i przeskoczyć do przerwy;
            w czasie kalibracji: przerywa i wykorzystuje poprzednie wartości
            kalibZero i kalib10Proc (przydatne np. po restarcie procedury)
  * Backspace - gdy chcemy wrócić do przerwy przed aktualnym blokiem

Powiązane moduły i narzędzia:
  - AlphaProcessing w Pythonie -> zbiera EEG, analizuje w czasie
    rzeczywistym i przekazuje moc lewej i prawej półkuli za pośrednictwem
    Lab Stream Layer; obliczanie sumy / różnicy jest robione dopiero
    w tej procedurze!
  - Lab Stream Layer --> protokół do przesyłania przez sieć aktualnego
    poziomu asymetrii (od AlphaProcessing do tej procedury)

Zbierane dane:
  - W tej procedurze (w pliku badani\ImieNazwisko.osb):
    * parametry procedury (ilość i długość bloków)
    * przypisanie badanego do warunku badawczego
    * wartości wyliczone w trakcie kalibracji
    * statystyki sesji (min, max, std, mean asymetria)
    * skuteczność badanego (szybkość osiągnięcia progu, czas powyżej progu)
    * w warunku fake: informacja o tym która sesja była odczytywana
  - W tej procedurze (w plikach rejestry\ImieNazwisko.XX.YY.alfa):
    * poziomy alfy dla lewej i prawej półkuli (w tej kolejności,
      oddzielone spacją) dla sesji XX i bloku YY

  - W ActiView:
    * plik ImięNazwisko.sesjaXX.bdf: EEG + triggery
'''

from framework.latentmodule import LatentModule
import os, traceback, time, numpy, random, threading, re

from pylsl.pylsl import StreamInlet, resolve_byprop

## do komunikatów dla badacza na początku:
from Tkinter import Tk, Label, Entry, Button, W
import tkMessageBox
from tkFileDialog import askopenfilename

import labjackU3


class Main(LatentModule):
    
    def __init__(self):
        LatentModule.__init__(self)
        
        # przeładowanie kodowania na utf, żeby działały komunikaty
        # (Eclipse domyślnie ma utf, więc nie bylo tego widać wcześniej)
        import sys
        reload(sys).setdefaultencoding("utf-8")
        
        ''' -----------------------------------------------
            ------------  KONFIGURACJA OGÓLNA  ------------
            ----------------------------------------------- 

        Konfiguracja:
          * wartości domyślne znajdują się poniżej
          * mogą zostać nadpisane w pliku study.cfg (wspólny dla wszystkich)
          * wszystko może zostać nadpisane w pliku badanego ImieNazwisko.osb
            
          * równolegle można konfigurować sposób wyświetlania:
            pliki fullscreen.prc, windowed.prc w folderze study
        '''
        
        ''' ------------  DŁUGOŚĆ BADANIA  ------------ '''
        # czas trwania bloku kalibracji (w minutach)
        self.dlugKalibracji = 1.0
        # czas trwania pojedynczego bloku (w minutach)
        self.dlugBloku = 6.0
        # ilość bloków składających się na całą sesję
        self.iloscBlokow = 5
        
        # dlugosc zbierania spoczynkowej alfy
        # 2.0 oznacza 2 minuty przy otwartych
        #     + 2 minuty przy zamknietych oczach
        self.spoczynkowaAlfaCzas = 2.0
        
        
        ''' ------------  WYBÓR GRUPY BADAWCZEJ  ------------
            Trzy warunki:
            - A (asymetria): true feedback - maksymalizowanie RÓŻNICY
              mocy alfa R-L 
            - R (relaks): true feedback - maksymalizowanie SUMY mocy
              alfa L+R
            - F (fałszywy): false feedback - odtwarzanie zapisu
              aktywności innej osoby z innej sesji prawdziwego feedbacku

            Grupy (A = 9xA; F = 3xF, R = 6xR)
            - AFR
            - ARF
            - FAR
            - FRA
            - RAF
            - RFA
        '''
        self.grupy = ["AAAAAAAAAFFFRRRRRR",  # AFR
                      "AAAAAAAAARRRRRRFFF",  # ARF
                      "FFFAAAAAAAAARRRRRR",  # FAR
                      "FFFRRRRRRAAAAAAAAA",  # FRA
                      "RRRRRRAAAAAAAAAFFF",  # RAF
                      "RRRRRRFFFAAAAAAAAA"]  # RFA
        self.grupa = random.choice(self.grupy)
        
        
        ''' ------------  FOLDERY I PLIKI  ------------ '''
        # folder z plikami konfiguracyjnymi osób badanych
        self.folderBadani = 'studies\\Neurofeedback\\badani'
        # folder z zapisami przebiegów sesji
        self.folderRejestry = 'studies\\Neurofeedback\\rejestry'
        # nazwy odpowiednich plików z rysunkami
        self.plikPasek = 'Picture0.png'
        self.plikKula1 = 'Picture1.png'
        self.plikKula2 = 'Picture5.png'
        self.plikKula3 = 'Picture10.png'


        ''' ------------  ELEMENTY WYŚWIETLANE  ------------ '''
        # parametry wyświetlanego ruchomego paska
        self.pasekSzerokosc = 0.05
        self.pasekMinDlugosc = 0.17  #pasek ma wymiary 174x613 = 0.05x0.17
        
        # poziom linii zerowej: (0 = środek ekranu; -0.6 = 60% poniżej środka
        # ekranu = 20% całej wysokości od dołu ekranu)
        self.poziomZero = -0.6   # NIE TESTOWAŁEM DLA INNYCH WARTOŚCI!
        
        # poziomy na których pojawiają się różne kule (j.w.)
        self.pozKula1 = 0.0
        self.pozKula2 = 0.2
        self.pozKula3 = 0.4
        
        self.punktyKula1 = 1.0
        self.punktyKula2 = 5.0
        self.punktyKula3 = 10.0
        
        # odleglość od krawędzi, w której pojawia się kula
        self.startKula = -0.1
        # rozmiar kuli
        self.kulaRozmiar = 0.06
        
        # odległość pokonywana przez kulki w czasie jednego "odświeżenia"
        # (2.0 = cała szerokość ekranu)
        self.kuleRuch = 0.003
        # częstotliwość aktualizacji kuleczek (w Hz)
        self.kuleCzestotliwosc = 20
        # w każdym kroku będziemy losować czy ma pojawić się kolejna kula
        # -- ta zmienna określa próg poniżej którego pokazujemy nową kulę
        # przy założeniu: rand(0,1)
        # losowanie odbywa się z częstotliwością self.kuleCzestotliwosc
        self.kulePrawdopod = 0.04
        
        # wysokość na której pojawia się punktacja
        self.poziomPunkty = 0.8
        # czcionka wykorzystywana do wyświetlania punktacji
        self.punktyCzcionka = self._engine.base.loader.loadFont('Helvetica.ttf')
        self.punktyRozmNormalny = 0.08
        self.punktyRozmWiekszy = 2 * self.punktyRozmNormalny
        self.punktyKolor = (0.0, 0.0, 0.0, 1.0)
        self.punktyZmianaKolor = (0.0, 0.0, 1.0, 1.0)
        self.punktyCzasWiekszy = 3.0
        
        self.czasNaRysowanie = 0.02
        
        
        ''' ------------  TRIGGERY  ------------
            * 1 - Początek kalibracji
            * 2 - Początek bloku/koniec przerwy
            * 3 - Koniec bloku/początek przerwy
            * 4 - Zmiana wyświetlanego poziomu na ekranie
            
            TRIGGERY POJAWIAJA SIE W KOLEJNOSCI:
            1 9 8 9
            3
            2 4 4 4 4 ... 4 3   x ilość bloków
            5 7 6 7
        '''
        self.triggerKalibracja = 1
        self.triggerKalibracjaZamkniete = 8
        self.triggerKalibracjaKoniec = 9
        self.triggerBlok = 2
        self.triggerPrzerwa = 3
        self.triggerZmianaPoziomu = 4
        
        self.triggerSpoczynkowaAlfaOtwarte = 5
        self.triggerSpoczynkowaAlfaZamkniete = 6
        # koniec jest zarówno po oczach otwartych jak i po zamknietych
        # (bo pomiedzy jednym i drugim jest instrukcja)
        self.triggerSpoczynkowaAlfaKoniec = 7
        
        
        ''' ------------  DOMYŚLNE USTAWIENIA OSOBY BADANEJ  ------------ '''
        # aktualny numer sesji (1 dla nowej osoby badanej)
        self.nrSesji = 1
        self.imieNazwisko = ""
        self.plikBadanego = ""
        # A = Adaptacja; R = Relaks; F = Fałszywy (szczegółowy opis
        # znajduje się wyżej) ustalany na podstawie self.grupa
        self.warunek = "A"
        # punktacja aktualna i archiwalna
        self.punktacja = 0.0
        self.punktacjaArch = []
        
        
        ''' ------------------------------------------------------
            ------------  ZMIENNE GLOBALNE PROCEDURY  ------------
            ------------------------------------------------------ 
        '''
        
        self.poziomAKTUALNY = self.poziomZero
        # zbiór wszystkich poziomów LEWEJ/PRAWEJ alfy
        self.poziomyLEWY = []
        self.poziomyPRAWY = []
        # zbiór wszystkich wartości wyliczonych poziomów
        # (i wyświetlanych użytkownikowi w true feedback)
        self.poziomyFINAL = []
        # czy dopisywać wartości do powyższych list 
        self.saveLP = False
        self.saveFinal = False
        
        # indeks pierwszego elementu z aktualnego bloku (w powyższych listach)
        self.poczatekBloku = 0
        
        # wyniki kalibracji, potrzebne do skalowania
        self.kalibZero = 0.0
        self.kalib10Proc = 0.1
        # obsługa klawiszy do sterowania procedurą
        self.wcisnietyKlawisz = ""
        
        # strumień LabStreamLayer do odbierania poziomów alfy
        self.strumien = None
        
        ''' pileczki '''
        # lista przechowująca kule aktualnie wyświetlane na ekranie
        # kula = klasa Kula na dole pliku
        self.kuleLista = []
        
        # wątek w którym obsługiwane są kule + stopped: zmienna wskazująca
        # głównej pętli, że powinna się przerwać
        self.kuleWorker = None
        self.kuleStopped = False
        
        # wątek w którym obsługiwane jest czytanie z Lab Stream Layer
        # + stopped: zmienna wskazująca głównej pętli, że powinna się przerwać
        self.poziomyWorker = None
        self.poziomyStopped = False
        
        # wątek w którym obsługiwane jest zmniejszenie czcionki wyniku
        # + punktyTimeStop: czas kiedy powinno się zmniejszyć
        self.punktyWorker = None
        self.punktyTimeStop = False
        self.punktyObiekt = None
        self.punktyZmianaObiekt = None
        
        # do sesji fake (szablon wczytywanych plikow i zawartosc plikow)
        self.fakeRejestr = ''
        # w postaci [ [ blok1asym1, blok1asym2, blok1asym3, ... ],
        #             [ ... ], [ ... ]  ]
        self.fakeBloki = []
        
        ''' -------------------------------------------------
            ------------  USTAWIENIA POCZĄTKOWE  ------------
            ------------------------------------------------- 
        '''
        
        # przypisanie zdarzeń dla obsługiwanych klawiszy
        self.accept("enter", self.obsluz_klawisz, ["enter"])
        self.accept("backspace", self.obsluz_klawisz, ["backspace"])
        
        # ustawienie białego tła
        self._engine.base.setBackgroundColor(1,1,1)

        # inicjalizacja karty do triggerów!
        labjackU3.configure()


    def run(self):
        ''' ----------------------------------------------------------------- 
            -------------------- INICJALIZACJA PROCEDURY --------------------
            ----------------------------------------------------------------- '''
        # wczytaj plik badanego lub stwórz nowy
        self.begin_user_file()
        
        # ustalanie warunku na aktualną sesję
        # jeżeli zdarzy się nadmiarowa sesja to będzie to domyślna wartość czyli "A"
        if len(self.grupa) >= self.nrSesji:
            self.warunek = self.grupa[self.nrSesji-1]
        
        # zapisywanie informacji o początku sesji do pliku
        self.write_to_subject_file('\n\n##### Początek sesji ' + str(self.nrSesji) + ' -- ' +
                           time.strftime("%d.%m.%Y %H:%M:%S") + ' ##### \n' +
                           '### Parametry sesji:\n' + 
                           '# warunek = ' + str(self.warunek) +
                           '\n# dlugKalibracji = ' + str(self.dlugKalibracji) +
                           '\n# iloscBlokow = ' + str(self.iloscBlokow) + 
                           '\n# dlugBloku = ' + str(self.dlugBloku) + '\n',
                           'Informacje o nowej sesji')
        
        # WCZYTYWANIE PLIKÓW Z ZAPISEM SESJI -- w pierwszym wierszu mogą być:
        # albo jedna wartość (plik z poprzedniej wersji, zmiana poziomu = 1 Hz)
        # albo dwie wartości (nowa wersja, zmiana poziomu = ok. 10 Hz)
        if self.warunek == "F":
            # sprawdzamy ktore pliki maja wiecej niz 20kB (sa z czestotliwoscia 10Hz):
            rejestryLista = filter(lambda x: os.path.getsize(x) > 20000L,
                                   [os.path.join(self.folderRejestry, x)
                                    for x in os.listdir(self.folderRejestry)])
            # wybieramy tylko te, w ktorych mamy 5 blok (czyli optymistycznie zakladajac
            # mamy wszystkie bloki ;)
            rejestryLista = filter(lambda x: re.search("^.*\.5\.alfa$", x), rejestryLista)
        
            # ze znalezionych zapisow losujemy jeden
            self.fakeRejestr = random.choice(rejestryLista)[:-6] + "%d.alfa"
        
            # zapisywanie informacji o pliku fake do pliku
            self.write_to_subject_file('# fakeRejestr = ' + self.fakeRejestr + '\n',
                                       'Informacja o pliku fake')
            
            # wczytywanie zapisanych blokow dla danej sesji:
            plikBlokNr = 1
            while True:
                try:
                    nazwaPliku = self.fakeRejestr % plikBlokNr
                    if not os.path.exists(nazwaPliku):
                        # plik nie istnieje, wiec istnialo tylko plikBlokNr-1 plikow
                        # wychodzimy z petli, bo nie ma co wiecej czytac
                        break
                    else:
                        with open(nazwaPliku,'r') as f:
                            print 'Wczytywanie bloku fake z pliku ' + nazwaPliku,
                            self.fakeBloki.append([])
                            # wczytywanie ustawien kalibracji
                            line = [float(number) for number in f.readline().split()]
                            self.kalibZero = line[0]
                            self.kalib10Proc = line[1]
                            for line in f.readlines():
                                line = [float(number) for number in line.split()]
                                self.fakeBloki[plikBlokNr-1].append( self.calculate_poziom(line[0], line[1]) )
                            print ' Zrobione.'
                    plikBlokNr += 1
                except Exception,e:
                    print 'Problem z wczytywaniem bloku fake z pliku "' + nazwaPliku + '".'
                    print e
                    traceback.print_exc()
        
        # uzyskanie dostępu do poziomów alfy przesyłanych przez sieć
        streams = resolve_byprop(prop = 'name', value = 'BCIAlphaLevel',
                                 timeout = 3)
        while len(streams) == 0:
            self.write("UWAGA! Procedura na laptopie nie zostala wlaczona!")
            streams = resolve_byprop(prop = 'name', value = 'BCIAlphaLevel',
                                     timeout = 3)
        self.strumien = StreamInlet(streams[0])
        
        # obrazki załaduj do cache:
        self.rysPasek = self.precache_picture(self.plikPasek)
        self.rysKula1 = self.precache_picture(self.plikKula1)
        self.rysKula2 = self.precache_picture(self.plikKula2)
        self.rysKula3 = self.precache_picture(self.plikKula3)
        
        # linia wyznaczająca poziom zerowy
        poziomZeroLinia = self.rectangle([-2,2,self.poziomZero+0.002,self.poziomZero-0.002],
                                         0,block=False,color=(.8,.8,.8,1))
        poziomZeroLinia.hide()
        
        # na początek tworzymy mały pasek, który później będzie przesuwany i skalowany
        pasek = self.picture(self.rysPasek, 0, block=False,
                             pos=(0.0, 1, self.poziomZero),
                             scale=(0.01, 1, 0.01))
        pasek.hide()
        
        
        print "PROCEDURA ZAINICJALIZOWANA! NACISNIJ SPACJE, ABY ROZPOCZAC"
        
        if self.nrSesji > 1 and len(self.punktacjaArch) > 0:
            self.write('Witaj na ' + str(self.nrSesji) +
                       ' sesji treningowej!\n\n' + 'Najlepszy twój wynik ' +
                       'z poprzednich sesji to ' + str(max(self.punktacjaArch)) + 
                       ' pkt.\nCzy uda ci się go dzisiaj pobić?\n\nPowodzenia!',
                       'space')
        elif self.nrSesji > 1 and not len(self.punktacjaArch) > 0:
            self.write('Witaj na ' + str(self.nrSesji) +
                       ' sesji treningowej!\n\n' + 'To twój pierwszy raz ' +
                       'z naszą grą.\nMiłej zabawy!',
                       'space')
        else:
            self.write('Witaj na pierwszej sesji treningowej!\n' +
                       'Rozpocznie się ona już niedługo.\n\n' +
                       'Przed rozpoczęciem upewnij się, że rozumiesz swoje zadanie.' +
                       '\nPowodzenia!', 'space')
                
        
        ''' ----------------------------------------------------------
            -------------------- WŁAŚCIWE BADANIE --------------------
            ---------------------------------------------------------- '''
        
        # przeprowadzenie kalibracji (wyliczenie kalibZero i kalib10Proc,
        # wykorzystywanych później do skalowania wysokości paska)
        self.perform_calibration()
        
        self.poziomyFINAL = []   #usuwamy dane z kalibracji
        
        # rysujemy początkową punktację
        self.punktyObiekt = self._engine.direct.gui.OnscreenText.\
                            OnscreenText(text = str(self.punktacja),
                                         pos = (0.0, self.poziomPunkty),
                                         scale = self.punktyRozmNormalny,
                                         font = self.punktyCzcionka,
                                         mayChange = True,
                                         fg = self.punktyKolor)
        self.punktyZmianaObiekt = self._engine.direct.gui.OnscreenText.\
                            OnscreenText(text = "",
                                         pos = (0.3, self.poziomPunkty),
                                         scale = self.punktyRozmNormalny,
                                         font = self.punktyCzcionka,
                                         mayChange = True,
                                         fg = self.punktyZmianaKolor)
        
        blok = 1
        while blok <= self.iloscBlokow:
            ## przerwa (wyświetlenie komunikatu i oczekiwanie na spację)
            labjackU3.trigger(self.triggerPrzerwa)
            
            self.write('Czas na chwilę przerwy! Przed tobą jeszcze ' +
                       str(self.iloscBlokow+1-blok) + ' z ' + 
                       str(self.iloscBlokow) + ' bloków.','space')
            
            for k in range(5,0,-1):
                self.write('Blok ' + str(blok) + '/' + str(self.iloscBlokow) + 
                           ' startujemy za '+ str(k)+'.')
            
            self.wcisnietyKlawisz = ""  # skasuj klawisze z przerwy
            koniecCzasu = time.time() + 60.0*self.dlugBloku
            
            # początek bloku: trigger, pasek i piłeczki
            labjackU3.trigger(self.triggerBlok)
            self.poziomy_start(saveLP = True, saveFinal = True)
            self.kule_start()
            pasek.show()
            poziomZeroLinia.show()
            
            if self.warunek == "F":
                # gdyby sie okazalo, ze wczytalismy mniej blokow niz
                # jest w aktualnej sesji (np. wczytalismy 5, a jest 6)
                # to bloki sie zapetla: jako 6 bedzie znow 1.
                fakeBlok = blok % len(self.fakeBloki)
                # aktualna wartosc z danego fake bloku
                probka = 0
                # kierunek w ktorym sie przesuwamy (gdyby sie okazalo, ze
                # braknie nam probek to zaczniemy sie cofac)
                kierunek = 1
                # wait
                wait = 5
            
            while time.time() < koniecCzasu:
                # kolejne poziomy alfy pobierają się w oddzielnym wątku
                
                ''' USTAL AKTUALNY POZIOM '''
                if self.warunek == "F":   ## FAKE FEEDBACK
                    poziom = self.skaluj_poziom(self.fakeBloki[fakeBlok][probka])
                    # zaobserwowane eksperymentalnie, ze w normalnym feedbacku
                    # nowe probki pojawiaja sie mniej wiecej co 5 aktualizacji ekranu
                    # (5 razy rysowany jest prostokat, ktory sie nie zmienia)
                    # -- tutaj jest to sztucznie wprowadzone dla fake feedbacku,
                    # zeby procedura skakala dokladnie tak szybko jak zwykla
                    wait -= 1
                    if wait <= 0:
                        wait = 5
                        if probka == len(self.fakeBloki[fakeBlok]):
                            kierunek = -1
                        elif probka == 0:
                            kierunek = 1
                        probka += kierunek
                
                else:  ## PRAWDZIWY FEEDBACK
                    poziom = self.skaluj_poziom(self.poziomAKTUALNY)
                
                aktualnaDlugosc = 0
                if poziom < self.poziomZero - self.pasekMinDlugosc:
                    # pasek nie może zejść poniżej linii 0, tylko przyczepia się do niej
                    aktualnaDlugosc = (self.poziomZero - poziom) / 2 + self.pasekMinDlugosc / 2
                    poziom = self.poziomZero - aktualnaDlugosc
                elif poziom > self.poziomZero + self.pasekMinDlugosc:
                    # powyżej linii 0 pasek rozciąga się (zmienia się jego długość i z tego
                    # powodu zmienia się również jego środek (zmienna poziom))
                    aktualnaDlugosc = (poziom - self.poziomZero) / 2 + self.pasekMinDlugosc / 2
                    poziom = self.poziomZero + aktualnaDlugosc
                
                ''' PRZERYSUJ EKRAN '''
                pasek.setPos(0.0, 1, poziom)
                pasek.setScale(self.pasekSzerokosc, 1,
                               max(self.pasekMinDlugosc, aktualnaDlugosc))
                # trigger zmiana wyswietlanego poziomu
                labjackU3.trigger(self.triggerZmianaPoziomu)
                self.refresh_screen()
                
                ''' OBSŁUGA KLAWISZY '''
                # przerywamy blok i idziemy do kolejnego
                if self.wcisnietyKlawisz == "enter":
                    self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
                    break
                # przerywamy blok i zaczynamy go od początku
                elif self.wcisnietyKlawisz == "backspace":
                    blok -= 1
                    self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
                    break
            
            ''' koniec bloku '''
            if self.warunek != "F":
                self.write_to_session_file(blok)  # zapisz przebieg bloku do pliku
            
            self.poziomy_stop()  # zatrzymujemy na czas przerwy
            self.kule_stop()  # zatrzymujemy na czas przerwy
            pasek.hide()  # usuwamy na czas przerwy
            poziomZeroLinia.hide()  # usuwamy na czas przerwy
        
            blok += 1   # przechodzimy do kolejnego bloku
        
        ''' koniec pętli - kończymy badanie '''
        # trigger przerwy na koniec ostatniego bloku
        # labjackU3.trigger(self.triggerPrzerwa)
        
        # kasujemy na koniec badania
        pasek.destroy()
        poziomZeroLinia.destroy()
        
        
        ''' ----------------------------------------------------------
            -------------------- SPOCZYNKOWA ALFA --------------------
            ---------------------------------------------------------- '''
        
        # chowamy punktację na czas zbierania asymetrii
        self.punktyObiekt.hide()
        
        ''' OTWARTE OCZY '''
        
        self.write('Już prawie koniec badania!\n' +
                   'Teraz zrelaksuj się i przez ' + str(self.spoczynkowaAlfaCzas) + 
                   ' min patrz na środek ekranu.', 'space')
        
        labjackU3.trigger(self.triggerSpoczynkowaAlfaOtwarte)
        
        punktFiks = self.crosshair(0,size=0.2,width=0.005,block=False)
        self.refresh_screen()
        self.wcisnietyKlawisz = ""  # skasuj klawisze wciśnięte do tej pory
        koniecCzasu = time.time() + 60.0*self.spoczynkowaAlfaCzas
        
        # pętla to wymuszenie odpowiednio długiego czasu + obsługa przycisku 
        while time.time() < koniecCzasu:
            self.refresh_screen()
            # przerywamy zbieranie danych do kalibracji
            if self.wcisnietyKlawisz == "enter":
                break
        
        if self.wcisnietyKlawisz == "enter":
            print("Zbieranie spoczynkowej alfy skrocone!")
        self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
        punktFiks.destroy()  #usuwamy punkt fiksacji, bo już niepotrzebny
        
        labjackU3.trigger(self.triggerSpoczynkowaAlfaKoniec)
        
        ''' ZAMKNIĘTE OCZY '''
        
        self.write('I ostatnia rzecz:\n' +
                   'Zamknij oczy na ' + str(self.spoczynkowaAlfaCzas) + 
                   ' min i zrelaksuj się :)', 'space')
        
        labjackU3.trigger(self.triggerSpoczynkowaAlfaZamkniete)
        
        self.refresh_screen()
        self.wcisnietyKlawisz = ""  # skasuj klawisze wciśnięte do tej pory
        koniecCzasu = time.time() + 60.0*self.spoczynkowaAlfaCzas
        
        # pętla to wymuszenie odpowiednio długiego czasu + obsługa przycisku 
        while time.time() < koniecCzasu:
            self.refresh_screen()
            # przerywamy zbieranie danych do kalibracji
            if self.wcisnietyKlawisz == "enter":
                break
        
        if self.wcisnietyKlawisz == "enter":
            print("Zbieranie spoczynkowej alfy skrocone!")
        self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
        
        labjackU3.trigger(self.triggerSpoczynkowaAlfaKoniec)
        
        
        # pokazujemy ponownie punktację
        self.punktyObiekt.show()
        
        # zakończenie badania
        self.study_summary()




    """ --------------------------------------
        ------------  KALIBRACJA  ------------
        -------------------------------------- """

    def perform_calibration(self):
        ''' Przez zadany czas zbieramy aktualny poziom; na koniec wyliczamy
            minimalny i maksymalny poziom w trakcie całej kalibracji i na ich
            podstawie wyliczamy kalib10Proc i kalibZero wykorzystywane później
            do skalowania wyświetlanego paska '''        
        
        print("Poczatek kalibracji...  "),
       
        for k in range(5,0,-1):
            self.write('Kalibracja startuje za '+str(k)+'.'+
                       '\nProszę patrz na + pośrodku ekranu i postaraj' +
                       ' się nie ruszać.')
        labjackU3.trigger(self.triggerKalibracja)
        
        punktFiks = self.crosshair(0,size=0.2,width=0.005,block=False)
        self.refresh_screen()
        
        self.poziomyFINAL = []
        self.strumien.pull_chunk()  # wyciągnij wszystkie próbki, które były do tej pory
        self.wcisnietyKlawisz = ""  # skasuj klawisze wciśnięte do tej pory
        koniecCzasu = time.time() + 60.0*self.dlugKalibracji
        # zaczynamy zbierać alfę
        self.poziomy_start(saveLP=False, saveFinal=True)
        
        # pętla to wymuszenie odpowiednio długiej kalibracji + obsługa przycisku 
        while time.time() < koniecCzasu:
            self.refresh_screen()
            # przerywamy zbieranie danych do kalibracji
            if self.wcisnietyKlawisz == "enter":
                break
        
        self.poziomy_stop()
        labjackU3.trigger(self.triggerKalibracjaKoniec)
        if self.wcisnietyKlawisz == "enter":
            # nie robimy nic; do kalibracji zostaje wartosc poprzednia,
            # wyliczona podczas poprzedniej sesji i zapisana w pliku (ew. domyślna)
            # (na wypadek np. przerwanej procedury, która została wznowiona)
            print("Kalibracja przerwana. Uzyte poprzednie wartosci")
        else:
            self.poziomyFINAL = numpy.sort(self.poziomyFINAL)
            kalibMean = numpy.mean(self.poziomyFINAL)
            kalibStd = numpy.std(self.poziomyFINAL)
            print("Kalibracja: Mean=" + str(kalibMean) + 
                  "  Std=" + str(kalibStd))
            
            # Jezeli to nie jest sesja Fake to zapisujemy parametry
            # (w sesji Fake zostaly juz one wczytane wczesniej z pliku)
            if self.warunek != "F":
                ## Mean = 20% od dołu ekranu
                ## 3SD  = 100% od dołu ekranu
                ## 10% wysokości = (3.0*kalibStd)/8.0
                self.kalib10Proc = (3.0*kalibStd)/8.0
                ## poziom zero (narysowany na ekranie w 20% wysokości ekranu):
                self.kalibZero = kalibMean
            
            #zapisujemy wyliczone wartości do pliku
            self.write_to_subject_file("# kalibStd = " + str(kalibStd) + 
                               "\n# kalibMean = " + str(kalibMean) + 
                               "\nkalibZero = " + str(self.kalibZero) +
                               "\nkalib10Proc = " + str(self.kalib10Proc) + '\n',
                               "Dane kalibracji")
        
        self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
        punktFiks.destroy()  #usuwamy punkt fiksacji, bo już niepotrzebny

        ''' ZAMKNIĘTE OCZY '''
        
        self.write('Teraz zamknij oczy i zrelaksuj sie :)', 'space')
        
        labjackU3.trigger(self.triggerKalibracjaZamkniete)
        
        self.refresh_screen()
        self.wcisnietyKlawisz = ""  # skasuj klawisze wciśnięte do tej pory
        koniecCzasu = time.time() + 60.0*self.dlugKalibracji
        
        # pętla to wymuszenie odpowiednio długiego czasu + obsługa przycisku 
        while time.time() < koniecCzasu:
            self.refresh_screen()
            # przerywamy zbieranie danych do kalibracji
            if self.wcisnietyKlawisz == "enter":
                break
        
        if self.wcisnietyKlawisz == "enter":
            print("Zbieranie poczatkowej alfy przy zamknietych oczach skrocone!")
        self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
        
        labjackU3.trigger(self.triggerKalibracjaKoniec)



    """ -------------------------------------------------------
        ------------  ZBIERANIE DANYCH PRZEZ SIEĆ  ------------
        ------------------------------------------------------- """

    def poziomy_start(self, saveLP, saveFinal):
        ''' Uruchom główną pętlę zbierania poziomów z LabStreamLayer
        '''
        self.saveLP = saveLP
        self.saveFinal = saveFinal
        self.strumien.pull_chunk()  # wyciągnij wszystkie próbki, które były w czasie przerwy
        self.poziomyWorker = threading.Thread(target=self.__poziomy_runner)
        self.poziomyWorker.start()
        
        
    def poziomy_stop(self):
        ''' Zatrzymaj główną pętlę zbierania poziomów z LabStreamLayer
        '''
        if( self.poziomyWorker is not None):
            self.poziomyStopped = True
            self.poziomyWorker.join()   # czeka aż wątek się zakończy
        
        
    def calculate_poziom(self, lewa, prawa):
        ''' Oblicz aktualny poziom na podstawie lewej i prawej alfy 
        '''
        
        # obliczanie poziomu alfy za Davidsonem 1995
        poziom = 0
        if self.warunek == "A" or self.warunek == "F":
            poziom = numpy.log10(prawa) - numpy.log10(lewa)
            #poziom = prawa - lewa
        elif self.warunek == "R":
            poziom = numpy.log10(prawa) + numpy.log10(lewa)
            #poziom = prawa + lewa
        return poziom
        

    def __poziomy_runner(self):
        """"Wczytaj kolejną próbkę z LabStreamLayer i oblicz aktualny poziom
            (na podstawie warunku)
        """
        while not self.poziomyStopped:
            sample,_timestamp = self.strumien.pull_sample()
            lewa = sample[0]
            prawa = sample[1]
            
            poziom = self.calculate_poziom(lewa, prawa)
            
            self.poziomAKTUALNY = poziom
            
            if self.saveLP:
                self.poziomyLEWY.append(lewa)
                self.poziomyPRAWY.append(prawa)
        
            if self.saveFinal:
                self.poziomyFINAL.append(poziom)
        
        # sprzątanie po wyjściu z pętli
        self.poziomyStopped = False



    """ ------------------------------------------
        ------------  OBSŁUGA PLIKÓW  ------------
        ------------------------------------------ """

    def begin_user_file(self):
        """ Wyświetl GUI i ustal czy to pierwsza czy kolejna sesja;
            jeśli pierwsza - stwórz nowy plik osoby badanej
            jeśli kolejna - wczytaj istniejący plik
        """
        Tk().withdraw() # nie chcemy GUI Tinkera; to polecenie nie pozwala głównemu oknu się pojawić
        
        result = tkMessageBox.askquestion("Konfiguracja", "Czy to jest pierwsza sesja osoby badanej?",
                                          icon='question')
        if result == 'yes':
            """ pierwsza sesja - podajemy nazwę pliku + losujemy grupę """
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
            self.write_to_subject_file('imieNazwisko = "' + str(self.imieNazwisko) + '"\n' +
                                       'grupa = "' + str(self.grupa) + '"\n',
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


    def study_summary(self):
        napisKoniec = self.write('To już koniec. Dziękujemy za udział w treningu.\n\n' +
                                 'Trwa zapis danych...',
                                 duration = 0, block = False)
        
        sredniPoziom = numpy.mean(self.poziomyFINAL)
        minPoziom = numpy.min(self.poziomyFINAL)
        maxPoziom = numpy.max(self.poziomyFINAL)
        odchStdPoziom = numpy.std(self.poziomyFINAL)
        
        self.write_to_subject_file("### Statystyki sesji:\n" + 
                           "# sredniPoziom = " + str(sredniPoziom) +
                           "\n# minPoziom = " + str(minPoziom) + 
                           "\n# maxPoziom = " + str(maxPoziom) + 
                           "\n# odchStdPoziom = " + str(odchStdPoziom) + "\n",
                           "Statystyki sesji")
        
        czasPowyzejProgu0 = len([i for i in self.poziomyFINAL if i >= 0.0])
        procPowyzejProgu0 = (100.0 * czasPowyzejProgu0) / len(self.poziomyFINAL)
        punktacjaMax = -1
        if len(self.punktacjaArch) > 0:
            punktacjaMax = max(self.punktacjaArch)
        self.punktacjaArch.append(self.punktacja) 
        
        self.write_to_subject_file("### Skuteczność:\n" + 
                           "## Czas powyżej progu 0 (w sek i w %)\n" +
                           "# czasPowyzejProgu0 = " + str(czasPowyzejProgu0) + "\n" +
                           "# procPowyzejProgu0 = " + str(procPowyzejProgu0) + "%\n" +
                           "## Punktacja\n" +
                           "# punktacja = " + str(self.punktacja) + "\n" +
                           "punktacjaArch = " + str(self.punktacjaArch) + "\n",
                           "Skutecznosc")
        
        self.write_to_subject_file("##### Koniec sesji " + str(self.nrSesji) + " -- " +
                           time.strftime("%d.%m.%Y %H:%M:%S") + ' ##### \n' + 
                           "\nnrSesji = " + str(self.nrSesji + 1) + '\n',
                           "Koniec zapisu sesji")
        
        napisKoniec.destroy()
        
        if self.nrSesji > 1 and self.punktacja > punktacjaMax:
            self.write('To już koniec. Dziękujemy za udział w treningu.\n\n' +
                       'Brawo! Udało ci się pobić twój rekord (' + 
                       str(punktacjaMax) + ' pkt)!\nZapraszamy na kolejne ' +
                       'sesje, na których może być jeszcze lepiej :)\n\n' + 
                       'Dane sesji zostały zapisane.',
                       duration = 0, block = False)
        elif self.nrSesji > 1 and not self.punktacja > punktacjaMax:
            self.write('To już koniec. Dziękujemy za udział w treningu.\n\n' +
                       'Niestety nie udało ci się pobić twojego rekordu ' + 
                       'wynoszącego ' + str(punktacjaMax) + ' pkt.\n' +
                       'Może kolejnym razem się uda :)\n\n' + 
                       'Dane sesji zostały zapisane.',
                       duration = 0, block = False)
        else:
            self.write('To już koniec. Dziękujemy za udział w treningu.\n\n' +
                       'Zapraszamy do udziału w kolejnych treningach\n i ' +
                       'próby pobicia dzisiejszego wyniku :)\n\n' + 
                       'Dane sesji zostały zapisane.',
                       duration = 0, block = False)

    
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
            self.imieNazwisko = entry.get()
            top.withdraw()  #schowaj okienko
            top.quit()      #wyjdź z pętli GUI i wróć do procedury


    def write_to_session_file(self, blok):
        ''' zapisz przebieg bloku (wszystkie poziomy lewej i prawej alfy)
            do pliku rejestry/ImieNazwisko.XX.YY.alfa
            (XX - sesja, YY - alfa)
            pierwszy wiersz to: kalibZero kalib10Proc 
            
            sesje Relaks zapisywane są w plikach .relaks, żeby później
            ich nie wczytywać w warunku FAKE!
        ''' 
        rozszerzenie = ".alfa"
        if self.warunek == "R":
            rozszerzenie = ".relaks"
        nazwaPliku = self.folderRejestry + "\\" + self.imieNazwisko + "." + \
                     str(self.nrSesji) + "." + str(blok) + rozszerzenie  
        
        try:
            if os.path.exists(nazwaPliku):
                print 'Plik "' + nazwaPliku + '" juz istnieje. Nadpisywanie pliku!'
            with open(nazwaPliku,'w') as f:
                print "Zapisywanie poziomow z bloku " + str(blok) + " do pliku...",
                f.write(str(self.kalibZero) + " ")
                f.write(str(self.kalib10Proc) + "\n")
                for i in range(self.poczatekBloku, len(self.poziomyLEWY)):
                    f.write(str(self.poziomyLEWY[i]) + " " + str(self.poziomyPRAWY[i]) + "\n")
                self.poczatekBloku = len(self.poziomyLEWY)  # przesuwamy znacznik na poczatek kolejnego bloku
                print 'Zrobione.'
        except Exception,e:
            print 'Problem z zapisywaniem informacji do pliku "' + nazwaPliku + '".'
            print e
            traceback.print_exc()


    def write_to_subject_file(self, text, comment):
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



    """ ----------------------------------------------
        ------------  FUNKCJE POMOCNICZE  ------------
        ---------------------------------------------- """

    def obsluz_klawisz(self, klawisz):
        self.wcisnietyKlawisz = klawisz

    def refresh_screen(self):
        self.sleep(self.czasNaRysowanie) #czas na przerysowanie ekranu

    def skaluj_poziom(self, poziom):
        return (poziom - self.kalibZero) / \
               (10.0 * self.kalib10Proc) + self.poziomZero


    ''' ---------------------------------------------------------------
        ---------------------- LATAJĄCE PIŁECZKI ----------------------
        --------------------------------------------------------------- '''
    def kule_start(self):
        ''' Uruchom główną pętlę kuleczek
        '''
        self.kuleWorker = threading.Thread(target=self.__kule_runner)
        self.kuleWorker.start()
        
        
    def kule_stop(self):
        ''' Zatrzymaj główną pętlę programu
        '''
        if( self.kuleWorker is not None):
            self.kuleStopped = True
            self.kuleWorker.join()   # czeka aż wątek się zakończy


    def __kule_runner(self):
        ''' Główna pętla programu obsługująca rysowanie kuleczek 
        '''
        while not self.kuleStopped:
            
            for k in self.kuleLista:
                # przesuwanie kuleczki
                k.pozPoziom += k.kierunek * self.kuleRuch
                k.obiekt.setFluidPos(k.pozPoziom, 1, k.pozPion)
                    
                if k.pozPoziom * (-k.kierunek) < 0:
                    # kuleczka przekracza środek ekranu:
                    # zmniejszamy i kasujemy, gdy bardzo mała
                    # domyślny rozmiar to 0.06
                    newSkala = k.obiekt.getScale()[0] - 0.005
                    if newSkala < 0.01:
                        k.obiekt.destroy()
                        self.kuleLista.remove(k)
                    else:
                        k.obiekt.setScale(newSkala)
                
                else:
                    # czy kuleczka trafiła w pasek?
                    if abs(k.pozPoziom) - self.kulaRozmiar - \
                       self.pasekSzerokosc < 0 and \
                       k.pozPion-self.kulaRozmiar < \
                       self.skaluj_poziom(self.poziomAKTUALNY) + \
                       self.pasekMinDlugosc:
                        # aktualizujemy punktację
                        self.punktacja += k.punkty
                        
                        self.punktyObiekt.setText(str(self.punktacja))
                        self.punktyObiekt.setScale(self.punktyRozmWiekszy)
                        self.punktyTimeStop = time.time() + self.punktyCzasWiekszy
                        
                        self.punktyZmianaObiekt.setText("+" + str(k.punkty))
                        
                        if self.punktyWorker is None:
                            self.punktyWorker = threading.Thread(target=self.__punktacja_runner)
                            self.punktyWorker.start()
                        
                        # kasujemy kuleczkę
                        k.obiekt.destroy()
                        self.kuleLista.remove(k)
                    
                time.sleep(1.0 / self.kuleCzestotliwosc / ( len(self.kuleLista)+1 ) )
                    
            # losowanie nowej kuleczki
            if random.random() < self.kulePrawdopod:
                typ = random.randint(1,3)
                strona = ( random.randint(1,2) - 1.5 ) * 2  # +/- 1
                if typ == 1:
                    kula = Main.Kula(None, self.rysKula1, self.pozKula1,
                                     (1.0 - self.startKula) * strona,
                                     self.punktyKula1, -strona)
                elif typ == 2:
                    kula = Main.Kula(None, self.rysKula2, self.pozKula2,
                                     (1.0 - self.startKula) * strona,
                                     self.punktyKula2, -strona)
                else:
                    kula = Main.Kula(None, self.rysKula3, self.pozKula3,
                                     (1.0 - self.startKula) * strona,
                                     self.punktyKula3, -strona)
                
                kula.obiekt = self.picture(kula.rysunek, 0, block=False,
                                           pos=(kula.pozPoziom, 1, kula.pozPion),
                                           scale=self.kulaRozmiar)
                self.kuleLista.append(kula)
        
        # Sprzątanie po wyjściu z pętli
        for k in self.kuleLista:
            if k.obiekt is not None:
                k.obiekt.destroy()
        self.kuleLista = []
        self.kuleStopped = False
        pass
    
    def __punktacja_runner(self):
        while time.time() < self.punktyTimeStop:
            time.sleep(0.1)
        self.punktyObiekt.setScale(self.punktyRozmNormalny)
        self.punktyZmianaObiekt.setText("")
        self.punktyWorker = None
    
    class Kula():
        def __init__(self, obiekt, rysunek, pozPion, pozPoziom, punkty, kierunek):
            self.obiekt = obiekt
            self.rysunek = rysunek
            self.pozPion = pozPion
            self.pozPoziom = pozPoziom
            self.punkty = punkty
            self.kierunek = kierunek