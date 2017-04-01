# -*- coding: UTF-8 -*-

"""

Procedura: AlphaNeurofeedback
Autor: Krzysztof Kutt, 2016

Moduł odpowiedzialny za analizę EEG (BioSemi Active Two), obliczanie mocy alfy lewej i prawej
przedczołowej i wysyłanie jej do LabStreamLayer (drugi moduł odbiera poziomy i wyświetla 
odpowiednie wartości na ekranie).

UWAGA: Wymaga włączonego ActiView na tym samym komputerze!
W ActiView w zakładce TCP Server musi być ustawione TCP Subset na A1-A32 + Add 8 EX Electrodes

"""

import numpy as np
import threading
import os, traceback

from pylsl import StreamInfo, StreamOutlet
from pyactivetwo.pyactivetwo import ActiveTwo

import scipy as sp

from wyrm.types import Data
import wyrm.processing as proc


class EEGAnalyser():

    def __init__(self):
        '''inicjalizacja przydatnych wartości
        '''
        # w pliku ustawień jest możliwość nadpisania okna czasowego i czestotliwosci
        self.plikUstawien = 'NeurofeedbackEEGAnalyser\standard.cfg'
        
        self.OKNO_CZASOWE = 1.0  # długość okna (w s), z którego liczona jest moc alfy
        self.CZESTOTLIWOSC = 10  # (w Hz) jak często liczona jest moc alfy 
        
        self.kanaly_wszystkie = ['Fp1', 'AF3', 'F7', 'F3', 'FC1', 'FC5', 'T7', 'C3',
                                 'CP1', 'CP5', 'P7', 'P3', 'Pz', 'PO3', 'O1', 'Oz',
                                 'O2', 'PO4', 'P4', 'P8', 'CP6', 'CP2', 'C4', 'T8',
                                 'FC6', 'FC2', 'F4', 'F8', 'AF4', 'Fp2', 'Fz', 'Cz',
                                 'EX1', 'EX2', 'EX3', 'EX4', 'EX5', 'EX6', 'EX7', 'EX8']
        
        # kanały, które analizujemy (F3 i F4 za Davidsonem + Cz jako referencja)
        self.kanaly_do_analizy = ['F3', 'F4', 'Cz']
        # kanały, dla których obliczamy moc alfy
        self.kanal_lewy = ['F3']
        self.kanal_prawy = ['F4']
        self.kanal_referencja = 'Cz'

    
    def start(self):
        '''główna funkcja programu zbierająca EEG i rozpoczynająca analizę
        '''
        
        ''' -----------------------------------------------------------
            ---------------------- INICJALIZACJA ----------------------
            -----------------------------------------------------------'''
        
        # strumień wyjściowy LabStreamLayer do wysyłania poziomów alfy
        info = StreamInfo('BCIAlphaLevel', 'Markers', 2, 0, 'float32',
                          'neurolab-laptop-1')
        self.strumien = StreamOutlet(info)
        
        host = '127.0.0.1'  # host na ktorym jest wlaczone ActiView
        port = 8888         # port na ktorym nasluchuje ActiView
        freq = 256          # czestotliwosc probkowania (ustalane w ActiView)
        channels = 40       # liczba kanalow wysylanych przez TCP (wyswietlane w AV)
        tcpsamples = 2      # liczba pakietow na jedna probke (wyswietlane w AV)
        
        # połączenie z BioSemi
        device = ActiveTwo(host=host, sfreq=freq, port=port, nchannels=channels,
                           tcpsamples=tcpsamples)
        
        
        try:
            if not os.path.exists(self.plikUstawien):
                print 'Plik ustawień "' + self.plikUstawien + '" nie znaleziony.'
            else:
                with open(self.plikUstawien,'r') as f:
                    print 'Wczytywanie parametrow z pliku ustawien...',
                    for line in f.readlines():
                        exec line in self.__dict__
                    print 'Zrobione.'
        except Exception,e:
            print 'Problem z wczytywaniem informacji z pliku "' + self.plikUstawien + '".'
            print e
            traceback.print_exc()
        
        print self.OKNO_CZASOWE
        print self.CZESTOTLIWOSC
        
        ''' -----------------------------------------------------------
            ------------------- CIĄGŁA ANALIZA EEG --------------------
            -----------------------------------------------------------'''
        
        self.dane_all = np.empty((0,channels))
        while True:
            # odczytaj dane z BioSemi
            rawdata = device.read(duration=1.0/self.CZESTOTLIWOSC)
            # dodaj dane do tablicy zbiorczej
            self.dane_all = np.concatenate((self.dane_all, rawdata), axis=0)
            # skróć tablicę jeśli jest dłuższa niż okno czasowe:
            if len(self.dane_all) > self.OKNO_CZASOWE * freq:
                self.dane_all = self.dane_all[-self.OKNO_CZASOWE * freq:]
            
            # wprowadz dane do struktury Data (z pakietu wyrm)
            # czas jest zawsze range(0,ilosc_probek), bo musi jakis byc
            data = Data(self.dane_all, [range(len(self.dane_all)),
                                        self.kanaly_wszystkie],
                        ['czas', 'kanal'], ['ms','nazwa'])
            data.fs = freq
            
            # analizę odsyłamy do osobnego wątku (będzie równolegle
            # z pobieraniem kolejnej próbki)
            t = threading.Thread(target=self.analizujEEG, args=(data,))
            t.start()
            
        
        
    def analizujEEG(self, data):
        '''funkcja odpowiedzialna za analizę EEG:
           - wyciągnięcie odpowiednich kanałów
           - obliczenie mocy alfy dla tych kanałów
           - wysłanie obliczonych wartości do LabStreamLayer
        '''
        
        # wycinamy tylko potrzebne kanały i ustalamy referencję
        data = proc.select_channels(data, self.kanaly_do_analizy)
        data = proc.rereference(data, self.kanal_referencja)
        
        # wycinamy odpowiednie kanały
        data_lewy = proc.select_channels(data, self.kanal_lewy)
        data_prawy = proc.select_channels(data, self.kanal_prawy)
        
        # nakładamy okno Hanninga
        window = sp.hanning(len(data_lewy.data))
        data_lewy.data = np.array([a*b for a,b in zip(data_lewy.data,window)])
        data_prawy.data = np.array([a*b for a,b in zip(data_prawy.data,window)])
        
        # obliczamy transformatę Fouriera
        data_lewy = proc.spectrum(data_lewy)
        data_prawy = proc.spectrum(data_prawy)
        
        # obliczamy moc (sumując wartości z przedziału 8-12 Hz)
        # data[0] = 1 Hz; data[7] = 8 Hz
        [moc_lewy] = sum(data_lewy.data[7:11])
        [moc_prawy] = sum(data_prawy.data[7:11])
        
        # wrzuć poziomy do strumienia
        self.strumien.push_sample([moc_lewy, moc_prawy])
        print str(moc_lewy) + "  " + str(moc_prawy)



if __name__ == '__main__':
    EEGAnalyser().start()

