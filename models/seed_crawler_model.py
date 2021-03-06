#This class provide APIs for interfaces applications
#to communicate with seed crawler
#
#03/11/2015

from subprocess import call
from subprocess import Popen
from subprocess import PIPE
from os import chdir, listdir, environ
from os.path import isfile, join, exists
import shutil
import sys

from seeds_generator.download import download, decode
from seeds_generator.concat_nltk import get_bag_of_words
from elastic.search_documents import get_context, term_search, search
from elastic.add_documents import update_document
from elastic.get_mtermvectors import getTermStatistics
from ranking import tfidf, rank, extract_terms


class SeedCrawlerModel:
    #Note: we should estimate the latency of each operation so that the application could adapt smoothly

    def __init__(self, urls = []):
        #Intermediate data will being handled here: urls, extracted text, terms, clusters, etc.

        #list of urls and their labels, ranking scores
        #e.g: urls = [["nature.com", 1, 0.9], ["sport.com", 0, 0.01]
        #list of terms and their labels, ranking scores
        #e.g: terms = [["science", 1, 0.9], ["sport", 0, 0.02]]
        self.urls_set = set(urls)
        self.positive_urls_set = set()
        self.negative_urls_set = set()
        self.tfidf = tfidf.tfidf()
        self.memex_home = environ['MEMEX_HOME']

 
    def submit_query_terms(self, term_list, max_url_count = 15, parallel_cb = None, cached=True):
    #Perform queries to Search Engine APIs
    #This function only operates when there is no information associated with the terms,
    #usually before running extract_terms()
    #
    #Args:
    #   term_list: list of search terms that are submited by user
    #Returns:
    #   urls: list of urls that are returned by Search Engine

        print '\n\nsubmit_query_terms\n\n'

        chdir(self.memex_home + '/seed_crawler/seeds_generator')
        
        query = ' '.join(term_list)
        with open('conf/queries.txt','w') as f:
            f.write(query)
            
        if not cached:
            comm = "java -cp target/seeds_generator-1.0-SNAPSHOT-jar-with-dependencies.jar BingSearch -t " + str(max_url_count)
            p=Popen(comm, shell=True, stdout=PIPE)
            output, errors = p.communicate()
            print output
            print errors

        
            call(["rm", "-rf", "html"])
            call(["mkdir", "-p", "html"])
            call(["rm", "-rf", "thumbnails"])
            call(["mkdir", "-p", "thumbnails"])
        
            #if sys.platform in ['darwin', 'linux2']:
            if sys.platform in ['darwin']:
                download("results.txt")
            else:
                download("results.txt", True, parallel_cb)

            if exists(self.memex_home + "/seed_crawler/ranking/exclude.txt"):
                call(["rm", self.memex_home + "/seed_crawler/ranking/exclude.txt"])

            with open("results.txt",'r') as f:
                urls = [self.validate_url(line.strip()) for line in f.readlines()]
        else:
            urls = search('text', term_list)[0:max_url_count]

        for url in urls:
            self.urls_set.add(url)

        self.tfidf = tfidf.tfidf(list(self.urls_set))

        return urls #Results from Search Engine
        
    
    def submit_selected_urls(self, positive, negative):
    #Perform ranking and diversifing on all urls with regard to the positive urls
    #
    #Args:
    #   labeled_urls: a list of pair <url, label>. Label 1 means positive and 0 means negative.
    #Returns:
    #   urls: list of urls with ranking scores

        # Test new positive and negative examples with exisitng classifier
        # If accuracy above threshold classify pages
        # Ranking 
        # Diversification
        
        print '\n\nsubmit_selected_urls\n\n'

        entries = []
        for pos_url in positive:
            entry = {
                'url': pos_url,
                'relevance': 1
            }
            entries.append(entry)
            
        for neg_url in negative:
            entry = {
                'url': pos_url,
                'relevance': 0
            }
            entries.append(entry)

        if len(entries) > 0:
            update_document(entries)

        other = []
        
        for url in positive:
            if url in self.urls_set:
                self.positive_urls_set.add(url)
                self.negative_urls_set.discard(url)

        for url in negative:
            if url in self.urls_set:
                self.negative_urls_set.add(url)
                self.positive_urls_set.discard(url)
                
        for url in self.urls_set:
            if (len(self.negative_urls_set) == 0) or (url not in self.negative_urls_set):
                if url not in self.positive_urls_set:
                    other.append(url)

        chdir(self.memex_home + '/seed_crawler/ranking')
        ranker = rank.rank()
        
        [ranked_urls,scores] = ranker.results(self.tfidf,self.positive_urls_set, other)
        return [ranked_urls, scores] # classified, ranked, diversified 

    def extract_terms(self, count):
    #Extract salient terms from positive urls
    #
    #Returns:        
    #   terms: list of extracted salient terms and their ranking scores
        
        print '\n\nextract_terms\n\n'

        chdir(self.memex_home + '/seed_crawler/ranking')
        if exists("selected_terms.txt"):
            call(["rm", "selected_terms.txt"])
        if exists("exclude.txt"):
            call(["rm", "exclude.txt"])

        extract = extract_terms.extract_terms(self.tfidf)
        return extract.getTopTerms(count)

    #def term_frequency(self):
     #   all_docs = get_bag_of_words(list(self.urls_set))
      #  return tfidf.tfidf(all_docs).getTfArray()

    def term_tfidf(self):
        urls = list(self.urls_set)
        [data, corpus] = getTermStatistics(urls)
        #all_docs = get_bag_of_words(list(self.urls_set))
        #return tfidf.tfidf(all_docs).getTfidfArray()
        return [urls, corpus, data.toarray()]

    def submit_selected_terms(self, positive, negative):
    #Rerank the terms based on the labeled terms
    #
    #Args:
    #   labeled_terms: list of pair of term and label: <term, label>. Label 1 means postive, 0 means negative.
    #Returns:
    #   terms: list of newly ranked terms and their ranking scores

        print '\n\nsubmit_selected_terms\n\n'

        terms = []
        chdir(self.memex_home+'/seed_crawler/ranking')
        
        past_yes_terms = []
        if exists("selected_terms.txt"):
            with open('selected_terms.txt','r') as f:
                past_yes_terms = [line.strip() for line in f.readlines()]

        with open('selected_terms.txt','w+') as f:
            for word in past_yes_terms:
                f.write(word+'\n')
            for choice in positive :
                if choice not in past_yes_terms:
                    f.write(choice+'\n')

        past_no_terms = []
        if exists("exclude.txt"):
            with open('exclude.txt','r') as f:
                past_no_terms = [line.strip() for line in f.readlines()]

        with open('exclude.txt','w+') as f:
            for word in past_no_terms:
                f.write(word+'\n')
            for choice in negative :
                if choice not in past_no_terms:
                    f.write(choice+'\n')

        extract = extract_terms.extract_terms(self.tfidf)
        [ranked_terms, scores] = extract.results(past_yes_terms + positive)

        ranked_terms = [ term for term in ranked_terms if (term not in past_no_terms) and (term not in negative)]
                
        return ranked_terms # ranked

    def term_context(self, terms):
        return get_context(terms)

    def validate_url(self, url):
        s = url[:4]
        if s == "http":
            return url
        else:
            url = "http://" + url
        return url


if __name__=="__main__":
    scm = SeedCrawlerModel([])
    urls =scm.submit_query_terms(["gun control"])
    
    print scm.term_context(sys.argv[1:])

    #scm.test()
    #Create a test that mimick user process here to test
    #1. User starts with some terms
    #2. (Repeat) User labels the urls and submits the labeled urls
    #3. User requests for extracting terms from labeled urls
    #4. (Repeat) User labels the terms and submits the labeled terms for reranking
