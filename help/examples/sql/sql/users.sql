/*!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19  Distrib 10.6.18-MariaDB, for debian-linux-gnu (x86_64)
--
-- Host: localhost    Database: machineDb
-- ------------------------------------------------------
-- Server version	10.6.18-MariaDB-0ubuntu0.22.04.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `users` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `login` varchar(50) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `user_level` int(11) NOT NULL,
  `last_login` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `user_group` varchar(50) NOT NULL,
  `token` varchar(45) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `login` (`login`),
  KEY `fk_user_level` (`user_level`),
  CONSTRAINT `fk_user_level` FOREIGN KEY (`user_level`) REFERENCES `user_levels` (`level`) ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=34 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,'dev_user','0b14d501a594442a01c6859541bcb3e8164d183d32937b851835442f69d5c94e',0,'2025-03-01 16:07:39','developers',''),(2,'admin','2e7442f1c3c1f6fc0b817748e27e2f1774aef7eb0647f7ee5292469e0844061d',1,'2025-03-01 19:44:48','admins','dfb268e8-c1b5-49bc-8ac4-f657104bd955'),(3,'admin2','804da2dbc2b9d7331b319995b78feca56572aad00243db0f2b10beba4c224d29',1,'2025-03-01 16:07:39','admins',''),(4,'operator1','55f1b11202e9d5adc8d9af5be6646c06c0b506196243f5b29c43325b371231b5',2,'2025-03-01 16:07:39','operators',''),(5,'operator2','43442b64ace8285c1c558c8ae67fcc226339e68802422d93ac8204c0c2c05f82',2,'2025-03-01 16:07:39','operators',''),(6,'user1','12654c024a4c0926329753cf79d4bb95d617c17684066809cf453b2084a4d5bc',3,'2025-03-01 16:07:39','users',''),(7,'user2','d6e5afe89ed25da45a4f3783ac4d9d961511eca9009d59efc257ed2af94ce901',3,'2025-03-01 16:07:39','users',''),(8,'user3','86291a08617e6340dd6019df34dc9ecc3d54f200de084f652be1a22da606aa20',3,'2025-03-01 16:07:39','users',''),(9,'user4','e83ae20db5ee02697b88a7b5ad63efbef8fbfa9b7821365a87f96261aad93ff7',3,'2025-03-01 16:07:39','users',''),(10,'user5','b6f20340fc1e2f4e012c0834de7411597de4be32cf0ff5824a2fb800ffae638b',3,'2025-03-01 16:07:39','users',''),(11,'vanya','2e7442f1c3c1f6fc0b817748e27e2f1774aef7eb0647f7ee5292469e0844061d',0,'2025-03-03 13:07:15','developers','43f95bf4-c4ad-4bc9-90e7-3806b5a22332'),(16,'developer','8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918',0,'2025-03-01 19:47:12','developers','2ccfc8e4-0941-4f05-91cb-4c0a00148a8a');
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-03-23 20:52:48
