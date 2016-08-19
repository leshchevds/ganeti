{-# OPTIONS_GHC -fno-warn-overlapping-patterns #-}
{-| network bandwidth data collector.

It collects the information about network speed between
the node groups.

-}

{-

Copyright (C) 2013, 2016 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}

module Ganeti.DataCollectors.Bandwidth
  ( dcName
  , dcVersion
  , dcFormatVersion
  , dcCategory
  , dcKind
  , dcReport
  , dcUpdate
  ) where

import Prelude ()
import Ganeti.Prelude

import qualified Data.Map as Map
import qualified Text.JSON as J
import qualified Control.Exception as E
import Control.Monad
import Data.Maybe (mapMaybe)
import System.Random
import System.Process

import qualified Ganeti.BasicTypes as BT
import qualified Ganeti.Constants as C
import Ganeti.Confd.ClientFunctions
import Ganeti.DataCollectors.Types
import Ganeti.Logging
import Ganeti.Objects
import Ganeti.Utils (readMaybe, exitIfBad)

-- | The name of this data collector.
dcName :: String
dcName = C.dataCollectorBandwidth

-- | The version of this data collector.
dcVersion :: DCVersion
dcVersion = DCVerBuiltin

-- | The version number for the data format of this data collector.
dcFormatVersion :: Int
dcFormatVersion = 1

-- | The category of this data collector.
dcCategory :: Maybe DCCategory
dcCategory = Nothing

-- | The kind of this data collector.
dcKind :: DCKind
dcKind = DCKPerf

-- | The data exported by the data collector, taken from the default location.
dcReport :: Maybe CollectorData -> IO DCReport
dcReport colData =
  let bandwidthData = case colData of
        Just (BandwidthData bmap) -> bmap
        _ -> Map.empty
  in buildDCReport bandwidthData

-- | default path to chunk-file, used to measure network bandwidth
defaultChunkPath :: String
defaultChunkPath = "/tmp/ganeti_bandwidth_chunk"

-- | default size (in megabytes) to chunk-file,
-- used to measure network bandwidth
defaultChunkSize :: Int
defaultChunkSize = 5

-- | Execute scp command and get it's time to work
bandwidthToHost :: String -> IO (Maybe Int)
bandwidthToHost hostname = do
  scp_stdout <- maybeReadProcess "/usr/bin/time"
                                  ["-f", "%e", "scp", "-q"
                                   , defaultChunkPath
                                   , "root@" ++ hostname ++ ":" ++
                                      defaultChunkPath ++ "_in"
                                   , "2>&1"]
  return $ case scp_stdout of
              Just stdout ->
                do
                  time <- readMaybe stdout :: Maybe Float
                  return $ round $ (fromIntegral defaultChunkSize * 8) / time
              Nothing -> Nothing

-- | Updates actual bandwidth to given host
updateHostBandwidth :: Map.Map String Int -> String -> IO (Map.Map String Int)
updateHostBandwidth bmap key = do
  bandwidth <- bandwidthToHost key
  return $ case bandwidth of
            Just v -> Map.insert key v bmap
            Nothing -> Map.delete key bmap

-- | Execute command and return stdout if command finished successfully
maybeReadProcess :: String -> [String] -> IO (Maybe String)
maybeReadProcess cmd params =
  ((E.try $ readProcess cmd params "") :: IO (Either IOError String)) >>=
    (\res -> case res of
              BT.Bad err ->
                do
                  logWarning $ "Bandwidth data collector error: " ++ err
                  return Nothing
              BT.Ok stdout ->
                  return $ Just stdout) . either (BT.Bad . show) BT.Ok

-- | Updates actual bandwidth to hosts in map
updateBandwidthMap :: Map.Map String Int -> IO (Map.Map String Int)
updateBandwidthMap bmap = do
  dd_res <- maybeReadProcess "dd" ["if=/dev/urandom",
                                   "of=" ++ defaultChunkPath,
                                   "bs=1M",
                                   "count=" ++ show defaultChunkSize]
  updatedMap <- case dd_res of
                  Just _ -> foldM updateHostBandwidth bmap hosts
                  Nothing -> return bmap
  _ <- maybeReadProcess "rm" [defaultChunkPath]
  return updatedMap
  where hosts = Map.keys bmap

-- | Used by newBandwidthMap with the random positive index
getByIdx :: Int -> [a] -> Maybe a
getByIdx idx l
  | null l = Nothing
  | otherwise = Just (l !! (idx `mod` length l) )

-- | Gets nodes and nodegroups from Confd server and creates new bandwidth map
newBandwidthMap :: IO (Map.Map String Int)
newBandwidthMap = do
  nd_answer <- BT.runResultT $ getNodes Nothing Nothing
  nmap <- exitIfBad "Can't get instance info from ConfD" nd_answer
  ndg_answer <- BT.runResultT $ getNodeGroups Nothing Nothing
  ngmap <- exitIfBad "Can't get instance info from ConfD" ndg_answer
  rand_idx <- randomRIO (0, Map.size nmap)
  updateBandwidthMap $
    let
      gnames = Map.keys ngmap
      nodes = Map.elems nmap
      candidates = map (\g -> [nodeName n | n <- nodes, nodeGroup n == g]) gnames
      targets = mapMaybe (getByIdx rand_idx) candidates
      res = zip targets [0, 0 ..]
    in Map.fromList res

-- | Updates the given Collector data.
-- extract all nesessary data (groups, nodes) if not loaded
dcUpdate :: Maybe CollectorData -> IO CollectorData
dcUpdate mcd = do
  curMap <- case mcd of
              Just (BandwidthData bmap) -> return bmap
              _ -> newBandwidthMap
  updMap <- updateBandwidthMap curMap
  return $ BandwidthData updMap

-- | This function computes the JSON representation of bandwidth map.
bandwidthToJson :: Map.Map String Int -> J.JSValue
bandwidthToJson bmap =
  let jmap = Map.map J.showJSON bmap
      blist = Map.toList jmap
  in J.JSObject (J.toJSObject blist)

-- | This function computes the DCReport for the CPU load.
buildDCReport :: Map.Map String Int -> IO DCReport
buildDCReport bmap =
  buildReport dcName dcVersion dcFormatVersion dcCategory dcKind dcRes
  where dcRes = bandwidthToJson bmap

